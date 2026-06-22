"""
A tiny private CA for mutually-authenticated TLS between the master and its
worker nodes. The master owns the CA key; it issues one server cert for itself
and one client cert per node. Both ends verify the other against this CA, so a
crafted client can't connect and the node can't be tricked onto a fake master.
"""
from __future__ import annotations

import datetime as _dt
import os
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

_CA_CN = "vadana-node-CA"
_YEAR = _dt.timedelta(days=365)


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _key_pem(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.TraditionalOpenSSL,
                             serialization.NoEncryption())


def _write(path: str, data: bytes):
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, 0o600)


def create_ca(directory: str) -> None:
    """Create ca.crt + ca.key in `directory`. Idempotent: keeps an existing CA."""
    os.makedirs(directory, exist_ok=True)
    crt, key = os.path.join(directory, "ca.crt"), os.path.join(directory, "ca.key")
    if os.path.exists(crt) and os.path.exists(key):
        return
    ca_key = _key()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _CA_CN)])
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - _dt.timedelta(minutes=1))
            .not_valid_after(now + 10 * _YEAR)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=True, crl_sign=True,
                                         encipher_only=False, decipher_only=False), critical=True)
            .sign(ca_key, hashes.SHA256()))
    _write(key, _key_pem(ca_key))
    _write(crt, cert.public_bytes(serialization.Encoding.PEM))


def issue_cert(directory: str, name: str, *, server: bool = False,
               out_prefix: str | None = None, sans: list[str] | None = None) -> tuple[str, str]:
    """Issue a leaf cert (client by default, serverAuth if server=True) signed by
    the CA. Returns (cert_pem, key_pem); if out_prefix is given, also writes
    `<out_prefix>.crt` / `.key` into `directory`."""
    ca_cert = x509.load_pem_x509_certificate(open(os.path.join(directory, "ca.crt"), "rb").read())
    ca_key = serialization.load_pem_private_key(
        open(os.path.join(directory, "ca.key"), "rb").read(), password=None)
    leaf_key = _key()
    eku = ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH
    now = _dt.datetime.now(_dt.timezone.utc)
    builder = (x509.CertificateBuilder()
               .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
               .issuer_name(ca_cert.subject)
               .public_key(leaf_key.public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(now - _dt.timedelta(minutes=1))
               .not_valid_after(now + 5 * _YEAR)
               .add_extension(x509.ExtendedKeyUsage([eku]), critical=False))
    if server:
        names = sans or ["localhost", "127.0.0.1"]
        alt = []
        for n in names:
            try:
                import ipaddress
                alt.append(x509.IPAddress(ipaddress.ip_address(n)))
            except ValueError:
                alt.append(x509.DNSName(n))
        builder = builder.add_extension(x509.SubjectAlternativeName(alt), critical=False)
    cert = builder.sign(ca_key, hashes.SHA256())
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = _key_pem(leaf_key).decode()
    if out_prefix:
        _write(os.path.join(directory, f"{out_prefix}.crt"), cert_pem.encode())
        _write(os.path.join(directory, f"{out_prefix}.key"), key_pem.encode())
    return cert_pem, key_pem


def fingerprint(cert_pem: str) -> str:
    """SHA-256 fingerprint (hex) of a PEM cert — the node's stable identity."""
    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    return cert.fingerprint(hashes.SHA256()).hex()


def server_ssl_context(directory: str) -> ssl.SSLContext:
    """Master-side context: present server.crt and REQUIRE a client cert that
    verifies against our CA."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(os.path.join(directory, "server.crt"), os.path.join(directory, "server.key"))
    ctx.load_verify_locations(os.path.join(directory, "ca.crt"))
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def client_ssl_context(ca_crt: str, cert: str, key: str) -> ssl.SSLContext:
    """Node-side context: present the node cert, verify the master against the CA.
    Hostname checking is off (the private CA + required client cert are the trust
    anchor, and the master IP may change)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_cert_chain(cert, key)
    ctx.load_verify_locations(ca_crt)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx

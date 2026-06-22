import os
import ssl

from bot import node_ca


def test_issue_and_verify(tmp_path):
    d = str(tmp_path)
    node_ca.create_ca(d)
    assert os.path.exists(os.path.join(d, "ca.crt"))
    assert os.path.exists(os.path.join(d, "ca.key"))

    cert, key = node_ca.issue_cert(d, "node-1")
    assert "BEGIN CERTIFICATE" in cert
    assert "BEGIN" in key and "PRIVATE KEY" in key
    assert len(node_ca.fingerprint(cert)) == 64  # sha256 hex

    # the issued client cert must chain to our CA
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(os.path.join(d, "ca.crt"))  # raises if ca.crt is malformed


def test_create_ca_idempotent(tmp_path):
    d = str(tmp_path)
    node_ca.create_ca(d)
    before = open(os.path.join(d, "ca.key")).read()
    node_ca.create_ca(d)  # second call must NOT regenerate the key
    assert open(os.path.join(d, "ca.key")).read() == before


def test_server_ssl_context_requires_client_cert(tmp_path):
    d = str(tmp_path)
    node_ca.create_ca(d)
    node_ca.issue_cert(d, "_server", server=True, out_prefix="server")
    ctx = node_ca.server_ssl_context(d)
    assert ctx.verify_mode == ssl.CERT_REQUIRED

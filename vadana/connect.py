from __future__ import annotations

import io
import ipaddress
import re
import time
import zipfile
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_DOMAIN_RE = re.compile(r"[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+")

def _public_host(host: str) -> bool:
    """True only for a routable public domain or IP. Blocks localhost and private /
    reserved / loopback / link-local ranges, so a crafted link can never make the
    server reach internal services (SSRF)."""
    if not host or host.lower() == "localhost" or host.endswith((".local", ".internal", ".lan")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return bool(_DOMAIN_RE.fullmatch(host))

def is_valid_recording(rec: "Recording") -> bool:
    """The input filter for every entry point (bot, API, CLIs). Accepts any Adobe
    Connect host — it isn't tied to IAU/Vadana — but the host must be a *public*
    domain/IP (never an internal address: SSRF), and the recording id and session
    token must be alphanumeric (no path-traversal or URL/header tricks)."""
    u = urlparse(rec.host or "")
    if u.scheme not in ("http", "https"):
        return False
    return bool(
        _public_host(u.hostname or "")
        and re.fullmatch(r"[A-Za-z0-9_-]+", rec.rec_id or "")
        and re.fullmatch(r"[A-Za-z0-9]*", rec.token or "")
    )

@dataclass
class Recording:
    """A recording identified by host, id and the session token from its URL."""
    host: str
    rec_id: str
    token: str

    @property
    def base_url(self) -> str:
        return f"{self.host}/{self.rec_id}/"

def parse_recording_url(url: str) -> Recording:
    """Accepts a full recording URL (preferably still carrying ?session=...)."""
    u = urlparse(url)
    host = f"{u.scheme}://{u.netloc}" if u.scheme else "https://" + url.split("/")[0]
    rec_id = u.path.strip("/").split("/")[-1]
    token = parse_qs(u.query).get("session", [""])[0]
    return Recording(host=host, rec_id=rec_id, token=token)

class ConnectClient:
    """Thin authenticated HTTP client for one Adobe Connect host."""

    def __init__(self, host: str, token: str, proxy: str | None = None):
        """proxy: optional HTTP/SOCKS proxy for reaching the (Iran-only) server,
        e.g. "socks5://user:pass@1.2.3.4:1080" or "http://1.2.3.4:8080".
        Used when the bot runs abroad and must route Vadana traffic via Iran."""
        self.host = host.rstrip("/")
        self.token = token
        s = requests.Session()
        s.verify = False
        s.cookies.set("BREEZESESSION", token)
        s.headers.update({"User-Agent": "Mozilla/5.0"})
        if proxy:
            s.proxies.update({"http": proxy, "https": proxy})
        self.session = s

    def _full(self, path: str) -> str:
        u = f"{self.host}{path if path.startswith('/') else '/' + path}"
        if not self.token:
            return u
        return f"{u}{'&' if '?' in u else '?'}session={self.token}"

    def get(self, path: str, timeout: int = 180, **kw) -> requests.Response:
        return self.session.get(self._full(path), timeout=timeout, **kw)

    _RETRY = (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
              requests.exceptions.ChunkedEncodingError, urllib3.exceptions.ProtocolError)

    def download_package_bytes(self, rec_id: str, progress=None, attempts: int = 3) -> bytes:
        """The offline recording ZIP: /<id>/output/<id>.zip?download=zip

        progress(downloaded_bytes, total_bytes) is called while streaming.
        Retries up to `attempts` times on a dropped connection (the Iran backhaul
        blips), backing off a little longer each time."""
        path = f"/{rec_id}/output/{rec_id}.zip?download=zip"
        for i in range(attempts):
            try:
                r = self.get(path, timeout=600, stream=True)
                if r.status_code != 200:
                    raise RuntimeError(f"could not download package (HTTP {r.status_code}). Session expired?")
                total = int(r.headers.get("content-length", 0))
                buf = io.BytesIO()
                got = 0
                for chunk in r.iter_content(65536):
                    if not chunk:
                        continue
                    buf.write(chunk)
                    got += len(chunk)
                    if progress:
                        progress(got, total)
                data = buf.getvalue()
                if data[:2] != b"PK":
                    raise RuntimeError("not a package (session expired or login page returned).")
                return data
            except self._RETRY:
                if i + 1 >= attempts:
                    raise
                time.sleep(2 * (i + 1))

    def open_package(self, rec_id: str, progress=None) -> zipfile.ZipFile:
        return zipfile.ZipFile(io.BytesIO(self.download_package_bytes(rec_id, progress)))

def read_member(zf: zipfile.ZipFile, name: str, encoding: str | None = "utf-8"):
    """Read one file from the package; text by default, bytes if encoding=None."""
    data = zf.read(name)
    return data.decode(encoding, "replace") if encoding else data

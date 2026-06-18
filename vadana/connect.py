"""
Shared access layer for IAU "Vadana" Adobe Connect recordings.

Handles: parsing a recording URL, an authenticated HTTP session (the server
uses a local/self-signed CA, so TLS verification is disabled on purpose), and
downloading the recording's offline package (a ZIP of FLV streams + XML).
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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
        s.verify = False  # local/self-signed CA on the university server
        s.cookies.set("BREEZESESSION", token)
        s.headers.update({"User-Agent": "Mozilla/5.0"})
        if proxy:
            s.proxies.update({"http": proxy, "https": proxy})
        self.session = s

    def _full(self, path: str) -> str:
        u = path if path.startswith("http") else f"{self.host}{path if path.startswith('/') else '/' + path}"
        return u + ("&" if "?" in u else "?") + "session=" + self.token

    def get(self, path: str, timeout: int = 180, **kw) -> requests.Response:
        return self.session.get(self._full(path), timeout=timeout, **kw)

    def download_package_bytes(self, rec_id: str, progress=None) -> bytes:
        """The offline recording ZIP: /<id>/output/<id>.zip?download=zip

        progress(downloaded_bytes, total_bytes) is called while streaming."""
        r = self.get(f"/{rec_id}/output/{rec_id}.zip?download=zip", timeout=600, stream=True)
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

    def open_package(self, rec_id: str, progress=None) -> zipfile.ZipFile:
        return zipfile.ZipFile(io.BytesIO(self.download_package_bytes(rec_id, progress)))


def read_member(zf: zipfile.ZipFile, name: str, encoding: str | None = "utf-8"):
    """Read one file from the package; text by default, bytes if encoding=None."""
    data = zf.read(name)
    return data.decode(encoding, "replace") if encoding else data

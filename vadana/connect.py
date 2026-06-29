from __future__ import annotations

import io
import ipaddress
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_DOMAIN_RE = re.compile(r"[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+")


def _public_host(host: str) -> bool:
    """True only for a routable public domain or IP. Blocks localhost and private /
    reserved / loopback / link-local ranges, so a crafted link can never make the
    server reach internal services (SSRF)."""
    if (
        not host
        or host.lower() == "localhost"
        or host.endswith((".local", ".internal", ".lan"))
    ):
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

    _RETRY = (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.ChunkedEncodingError,
        urllib3.exceptions.ProtocolError,
    )

    def _probe_size(self, url: str) -> int:
        """Returns the file size if the server supports HTTP range requests,
        otherwise returns 0."""
        probe = self.session.get(url, headers={"Range": "bytes=0-0"}, timeout=10)
        probe.raise_for_status()
        if probe.status_code != 206:
            return 0
        return int(probe.headers.get("content-range", "").split("/")[-1] or 0)

    def _fetch_chunk(
        self,
        url: str,
        start: int,
        end: int,
        attempts: int,
        progress,
        lock,
        state,
        worker_idx: int,
    ) -> bytes:
        """Downloads a single byte range with retries and reports its progress."""
        for attempt in range(attempts):
            buf = bytearray()
            state["downloaded_per_worker"][worker_idx] = 0

            try:
                r = self.session.get(
                    url,
                    stream=True,
                    headers={"Range": f"bytes={start}-{end}"},
                    timeout=30,
                )

                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        buf.extend(chunk)
                        if progress:
                            with lock:
                                state["downloaded_per_worker"][worker_idx] = len(buf)
                                progress(
                                    sum(state["downloaded_per_worker"]), state["total"]
                                )

                return bytes(buf)
            except self._RETRY:
                if attempt == attempts - 1:
                    raise
                time.sleep(2**attempt)

    def _download_concurrently(
        self, url: str, size: int, workers: int, attempts: int, progress
    ) -> bytes:
        """Splits the download into byte ranges and fetches them concurrently."""
        lock = threading.Lock()
        state = {"downloaded_per_worker": [0] * workers, "total": size}

        def worker_task(i):
            start = i * size // workers
            end = size - 1 if i == workers - 1 else (i + 1) * size // workers - 1
            return self._fetch_chunk(
                url, start, end, attempts, progress, lock, state, i
            )

        with ThreadPoolExecutor(max_workers=workers) as ex:
            return b"".join(ex.map(worker_task, range(workers)))

    def download_package_bytes(
        self, rec_id: str, progress=None, attempts: int = 3
    ) -> bytes:
        """Downloads the recording ZIP, using concurrent range requests when
        supported by the server, otherwise falling back to a single request."""
        url = self._full(f"/{rec_id}/output/{rec_id}.zip?download=zip")

        size = self._probe_size(url)

        if not size:
            data = self.session.get(url, timeout=600).content
        else:
            workers = min(8, max(1, size // (5 * 1024 * 1024)))
            data = self._download_concurrently(url, size, workers, attempts, progress)

        if data[:2] != b"PK":
            raise RuntimeError("Corrupt package or session expired.")
        return data

    def open_package(self, rec_id: str, progress=None) -> zipfile.ZipFile:
        return zipfile.ZipFile(
            io.BytesIO(self.download_package_bytes(rec_id, progress))
        )


def read_member(zf: zipfile.ZipFile, name: str, encoding: str | None = "utf-8"):
    """Read one file from the package; text by default, bytes if encoding=None."""
    data = zf.read(name)
    return data.decode(encoding, "replace") if encoding else data

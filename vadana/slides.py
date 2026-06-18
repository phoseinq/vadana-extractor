"""
Part 1 — download the ORIGINAL shared PDFs from a recording.

When a professor uploads a PPT/PDF into the Share pod, Connect keeps it as a
separate content object (not inside the recording streams). The recording's
mainstream.xml still records a `downloadUrl` for each shared file. We resolve
that to the real source path and download the untouched PDF.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse, parse_qs, unquote_plus, quote

from .connect import ConnectClient, read_member

_DOWNLOAD_RE = re.compile(r"<downloadUrl><!\[CDATA\[([^\]]+)\]\]></downloadUrl>")


def find_shared_files(mainstream_xml: str) -> list[tuple[str, str]]:
    """Return unique (source_base, filename) pairs in first-seen order.

    A downloadUrl looks like:
      /system/download?download-url=/_a7/<cid>/source/&name=<urlencoded name>
    The real file is served at <source_base><name>?download=true
    """
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for rel in _DOWNLOAD_RE.findall(mainstream_xml):
        if rel in seen:
            continue
        seen.add(rel)
        q = parse_qs(urlparse(rel).query)
        base = q.get("download-url", [""])[0]          # /_a7/<cid>/source/
        name = unquote_plus(q.get("name", ["file.pdf"])[0])
        if base:
            out.append((base, name))
    return out


def _safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "file"


CATEGORIES = {
    "doc": {".pdf", ".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx", ".txt"},
    "audio": {".mp3", ".wav", ".m4a", ".ogg", ".aac"},
    "video": {".mp4", ".mkv", ".mov", ".avi", ".flv", ".webm"},
    "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"},
}


def category_of(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    for cat, exts in CATEGORIES.items():
        if ext in exts:
            return cat
    return "other"


def download_slides(client: ConnectClient, rec_id: str, out_dir: str, zf=None,
                    progress=None, exts=None) -> list[str]:
    """Download every shared file of one recording into out_dir (any type, with
    its real name/extension). Returns saved paths.

    exts: optional set of lowercase extensions to keep (e.g. {".pdf"}); None = all.
    progress(done, total) is called after each item (for a progress bar)."""
    zf = zf or client.open_package(rec_id)
    try:
        xml = read_member(zf, "mainstream.xml")
    except KeyError:
        raise RuntimeError("mainstream.xml missing from package (unexpected layout)")

    items = find_shared_files(xml)
    if not items:
        return []

    os.makedirs(out_dir, exist_ok=True)
    total = len(items)
    saved: list[str] = []
    for i, (base, name) in enumerate(items, 1):
        ext = os.path.splitext(name)[1].lower()
        if exts is not None and ext not in exts:
            if progress:
                progress(i, total)
            continue
        r = client.get(f"{base}{quote(name)}?download=true", timeout=600)
        ct = r.headers.get("content-type", "").lower()
        # accept any real file; reject only login/error HTML pages
        ok = r.status_code == 200 and r.content and "text/html" not in ct
        if ok:
            path = os.path.join(out_dir, _safe_name(name))
            with open(path, "wb") as f:
                f.write(r.content)
            saved.append(path)
        if progress:
            progress(i, total)
    return saved

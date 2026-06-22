from __future__ import annotations

import io
import shutil
import zipfile

from vadana.slides import download_slides

def build_job_bundle(pkg_path: str, data: bytes, client, rec_id: str) -> None:
    with open(pkg_path, "wb") as f:
        f.write(data)
    tmp = pkg_path + ".pdfs"
    try:
        pdfs = download_slides(client, rec_id, tmp, zipfile.ZipFile(io.BytesIO(data)), None, {".pdf"}) or []
    except Exception:
        pdfs = []
    if pdfs:
        with zipfile.ZipFile(pkg_path, "a", zipfile.ZIP_STORED) as z:
            for i, p in enumerate(pdfs):
                z.write(p, f"_pdfs/{i:03d}.pdf")
    shutil.rmtree(tmp, ignore_errors=True)

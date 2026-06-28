"""
Optional HTTP API — turns the extractor into a small service.

    POST /extract   { "url": "<recording url with ?session=>", "kind": "files" | "whiteboard" }
        -> a ZIP of the shared files, or the whiteboard PDF
    GET  /health

Run:    uvicorn cli.api:app --host 0.0.0.0 --port 8000
Needs:  pip install fastapi uvicorn   (set IRAN_PROXY in the env when hosting abroad)
"""
from __future__ import annotations

import os
import tempfile
import zipfile

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from vadana.connect import parse_recording_url, ConnectClient, is_valid_recording
from vadana.slides import download_slides
from vadana import whiteboard as wb_mod

app = FastAPI(title="Vadana Extractor", version="3.4.7")


class ExtractRequest(BaseModel):
    url: str
    kind: str = "files"


def _client(url: str) -> tuple[ConnectClient, str]:
    rec = parse_recording_url(url)
    if not is_valid_recording(rec):                # any public Adobe Connect host; session optional
        raise HTTPException(400, "not a valid Adobe Connect recording url")
    proxy = os.environ.get("IRAN_PROXY") or None
    return ConnectClient(rec.host, rec.token, proxy=proxy), rec.rec_id


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/extract")
def extract(req: ExtractRequest):
    client, rec_id = _client(req.url)
    out = tempfile.mkdtemp(prefix="vadana_")
    try:
        if req.kind == "whiteboard":
            zf = client.open_package(rec_id)
            pdfs = download_slides(client, rec_id, os.path.join(out, "pdfs"), zf, exts={".pdf"}) or None
            pdf = os.path.join(out, f"{rec_id}_whiteboard.pdf")
            if not wb_mod.make_pdf(zf, pdf, pdf_paths=pdfs):
                raise HTTPException(404, "this recording has no whiteboard")
            return FileResponse(pdf, filename=os.path.basename(pdf), media_type="application/pdf")

        saved = download_slides(client, rec_id, out)
        if not saved:
            raise HTTPException(404, "this recording has no shared files")
        bundle = os.path.join(out, f"{rec_id}_files.zip")
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
            for p in saved:
                z.write(p, os.path.basename(p))
        return FileResponse(bundle, filename=os.path.basename(bundle), media_type="application/zip")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"extraction failed: {e}")

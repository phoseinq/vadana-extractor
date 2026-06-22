import zipfile

from bot import offload_bundle


def _rec_zip(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mainstream.xml", "<r></r>")
    return path.read_bytes()


def test_bundle_appends_pdfs_in_order(tmp_path, monkeypatch):
    data = _rec_zip(tmp_path / "rec.zip")
    p0 = tmp_path / "a.pdf"; p0.write_bytes(b"%PDF-0")
    p1 = tmp_path / "b.pdf"; p1.write_bytes(b"%PDF-1")
    # download_slides returns the PDFs in page order; the bundle must preserve it
    monkeypatch.setattr(offload_bundle, "download_slides", lambda *a, **k: [str(p0), str(p1)])
    pkg = str(tmp_path / "job.zip")
    offload_bundle.build_job_bundle(pkg, data, None, "rec")
    with zipfile.ZipFile(pkg) as z:
        names = z.namelist()
        assert "mainstream.xml" in names                  # original package intact
        assert "_pdfs/000.pdf" in names and "_pdfs/001.pdf" in names
        assert z.read("_pdfs/000.pdf") == b"%PDF-0"


def test_bundle_without_pdfs_is_just_the_zip(tmp_path, monkeypatch):
    data = _rec_zip(tmp_path / "rec.zip")
    monkeypatch.setattr(offload_bundle, "download_slides", lambda *a, **k: [])
    pkg = str(tmp_path / "job.zip")
    offload_bundle.build_job_bundle(pkg, data, None, "rec")
    with zipfile.ZipFile(pkg) as z:
        assert not any(n.startswith("_pdfs/") for n in z.namelist())


def test_bundle_survives_pdf_fetch_failure(tmp_path, monkeypatch):
    data = _rec_zip(tmp_path / "rec.zip")
    def boom(*a, **k):
        raise RuntimeError("iran proxy down")
    monkeypatch.setattr(offload_bundle, "download_slides", boom)
    pkg = str(tmp_path / "job.zip")
    offload_bundle.build_job_bundle(pkg, data, None, "rec")     # must not raise
    with zipfile.ZipFile(pkg) as z:
        assert "mainstream.xml" in z.namelist()

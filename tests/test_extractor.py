import os

import pytest

from vadana.slides import download_slides


def test_download_saves_all_files(fake_client, package, tmp_path):
    saved = download_slides(fake_client, "rec", str(tmp_path), zf=package)
    names = sorted(os.path.basename(p) for p in saved)
    assert names == ["Chapter 1.pdf", "notes.docx"]
    assert all(os.path.exists(p) for p in saved)
    assert all(u.endswith("?download=true") for u in fake_client.requested)


def test_download_extension_filter(fake_client, package, tmp_path):
    saved = download_slides(fake_client, "rec", str(tmp_path), zf=package, exts={".pdf"})
    assert [os.path.basename(p) for p in saved] == ["Chapter 1.pdf"]


def test_missing_mainstream_raises(fake_client, make_zip, tmp_path):
    z = make_zip({"indexstream.xml": "<r></r>"})
    with pytest.raises(RuntimeError):
        download_slides(fake_client, "rec", str(tmp_path), zf=z)


def test_no_shared_files_returns_empty(fake_client, make_zip, tmp_path):
    z = make_zip({"mainstream.xml": "<recording></recording>"})
    assert download_slides(fake_client, "rec", str(tmp_path), zf=z) == []


def test_dedup_same_file_different_urls(fake_client, make_zip, tmp_path):
    # Adobe Connect emits a fresh downloadUrl (different content-id / query) every
    # time a file is reshown; dedup is by filename so it isn't sent N times.
    xml = ("<recording>"
           "<downloadUrl><![CDATA[/system/download?download-url=/_a7/11/source/&name=Slides.pdf]]></downloadUrl>"
           "<downloadUrl><![CDATA[/system/download?download-url=/_a7/22/source/&name=Slides.pdf]]></downloadUrl>"
           "<downloadUrl><![CDATA[/system/download?download-url=/_a7/11/source/&name=Slides.pdf&v=2]]></downloadUrl>"
           "</recording>")
    z = make_zip({"mainstream.xml": xml})
    saved = download_slides(fake_client, "rec", str(tmp_path), zf=z)
    assert [os.path.basename(p) for p in saved] == ["Slides.pdf"]
    assert len(fake_client.requested) == 1


def test_rejects_html_login_page(make_client, package, tmp_path):
    client = make_client(content=b"<html>login</html>", ct="text/html")
    saved = download_slides(client, "rec", str(tmp_path), zf=package)
    assert saved == []                      # an HTML page = expired session, not a file

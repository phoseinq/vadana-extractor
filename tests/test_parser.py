import requests

from vadana.connect import parse_recording_url, ConnectClient
from vadana.slides import find_shared_files, category_of, _safe_name


def test_parse_full_url():
    rec = parse_recording_url("https://vadavc30.ec.iau.ir/lykiz9mc3wqp/?session=tok123&proto=true")
    assert rec.host == "https://vadavc30.ec.iau.ir"
    assert rec.rec_id == "lykiz9mc3wqp"
    assert rec.token == "tok123"


def test_parse_other_branch_without_session():
    # any IAU branch host is accepted, and the session is optional now
    rec = parse_recording_url("https://vadana14.ec.iau.ir/abc123/?proto=true")
    assert rec.host == "https://vadana14.ec.iau.ir"
    assert rec.rec_id == "abc123"
    assert rec.token == ""          # no ?session= is fine — many recordings open directly


def test_parse_base_url_property():
    rec = parse_recording_url("https://host.tld/rec9/?session=x")
    assert rec.base_url == "https://host.tld/rec9/"


def test_find_shared_files_dedupes_and_decodes(mainstream_xml):
    items = find_shared_files(mainstream_xml)
    assert items == [("/_a7/77/source/", "Chapter 1.pdf"),
                     ("/_a7/77/source/", "notes.docx")]


def test_find_shared_files_empty():
    assert find_shared_files("<recording></recording>") == []


def test_category_of():
    assert category_of("a.pdf") == "doc"
    assert category_of("b.MP3") == "audio"
    assert category_of("c.mkv") == "video"
    assert category_of("d.PNG") == "image"
    assert category_of("e.bin") == "other"


def test_safe_name_blocks_path_traversal():
    assert _safe_name("../../etc/passwd") == "passwd"
    assert _safe_name("..\\..\\win.ini") == "win.ini"
    assert _safe_name("..") == "file"
    assert _safe_name("") == "file"
    assert _safe_name('a:b*c?.pdf') == "a_b_c_.pdf"


class _Resp:
    status_code = 200
    headers = {"content-length": "4"}

    def __init__(self, fail):
        self.fail = fail

    def iter_content(self, _n):
        if self.fail:
            raise requests.exceptions.ConnectionError("Connection aborted, RemoteDisconnected")
        yield b"PK\x03\x04"


def test_download_retries_once_on_dropped_connection(monkeypatch):
    monkeypatch.setattr("vadana.connect.time.sleep", lambda *_: None)
    c = ConnectClient("https://vadavc30.ec.iau.ir", "")
    seq = iter([_Resp(fail=True), _Resp(fail=False)])     # first drops, second works
    monkeypatch.setattr(c, "get", lambda *a, **k: next(seq))
    assert c.download_package_bytes("rec")[:2] == b"PK"     # retried, then succeeded


def test_download_gives_up_after_attempts(monkeypatch):
    monkeypatch.setattr("vadana.connect.time.sleep", lambda *_: None)
    c = ConnectClient("https://vadavc30.ec.iau.ir", "")
    monkeypatch.setattr(c, "get", lambda *a, **k: _Resp(fail=True))
    try:
        c.download_package_bytes("rec", attempts=2)
        assert False, "should have raised"
    except requests.exceptions.ConnectionError:
        pass

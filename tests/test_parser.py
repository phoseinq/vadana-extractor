import requests

from vadana.connect import parse_recording_url, ConnectClient, is_valid_recording
from vadana.slides import find_shared_files, category_of, _safe_name


def test_is_valid_recording_filters_inputs():
    ok = [
        "https://vadavc30.ec.iau.ir/abc123/?session=tok9",    # IAU Vadana
        "https://vadana14.ec.iau.ir/xyz/",                    # session optional
        "https://connect.example.edu/meeting42/?session=t",   # any other Adobe Connect host
        "https://8.8.8.8/rec1/",                              # a public IP literal is fine
    ]
    for u in ok:
        assert is_valid_recording(parse_recording_url(u)), u
    bad = [
        "https://localhost/abc/",                             # internal host (SSRF)
        "https://127.0.0.1/abc/",                             # loopback (SSRF)
        "https://192.168.1.10/abc/?session=x",                # private LAN (SSRF)
        "https://10.0.0.5/abc/",                              # private (SSRF)
        "https://server.internal/abc/",                       # internal-only suffix (SSRF)
        "ftp://example.com/abc/",                             # non-http scheme
        "https://host.tld/p/4042/login.php",                  # rec_id has a dot
        "https://host.tld/abc/?session=a%0d%0ab",             # CRLF in the token
    ]
    for u in bad:
        assert not is_valid_recording(parse_recording_url(u)), u


def test_find_shared_files_rejects_offhost_base():
    # a crafted download-url pointing off-host must not be used (token-leak / SSRF)
    xml = ('<r><downloadUrl><![CDATA[/system/download?download-url=http://evil.com/'
           '&name=x.pdf]]></downloadUrl></r>')
    assert find_shared_files(xml) == []


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

from vadana.connect import parse_recording_url
from vadana.slides import find_shared_files, category_of, _safe_name


def test_parse_full_url():
    rec = parse_recording_url("https://vadavc30.ec.iau.ir/lykiz9mc3wqp/?session=tok123&proto=true")
    assert rec.host == "https://vadavc30.ec.iau.ir"
    assert rec.rec_id == "lykiz9mc3wqp"
    assert rec.token == "tok123"


def test_parse_url_without_session():
    rec = parse_recording_url("https://vadavc30.ec.iau.ir/abc123/")
    assert rec.rec_id == "abc123"
    assert rec.token == ""          # caller must reject links with no ?session=


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

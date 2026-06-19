import io
import zipfile

import pytest

from vadana import whiteboard as wb
from vadana import timeline as tl


def test_pdf_backgrounds_guards():
    assert wb.pdf_backgrounds([], [(0, 0)]) == {}
    assert wb.pdf_backgrounds(None, [(0, 0)]) == {}
    assert wb.pdf_backgrounds(["x.pdf"], []) == {}


def test_pdf_backgrounds_matches_page_count(tmp_path):
    pytest.importorskip("fitz")
    import img2pdf
    from PIL import Image
    pngs = []
    for c in ((255, 0, 0), (0, 255, 0)):
        b = io.BytesIO()
        Image.new("RGB", (40, 30), c).save(b, "PNG")
        pngs.append(b.getvalue())
    p = tmp_path / "two.pdf"
    p.write_bytes(img2pdf.convert(pngs))
    bg = wb.pdf_backgrounds([str(p)], [(0, 0), (0, 1)])     # 2 pages, 2 keys -> match
    assert set(bg) == {(0, 0), (0, 1)}
    assert wb.pdf_backgrounds([str(p)], [(0, 0), (0, 1), (0, 2)]) == {}   # page-count mismatch


def test_build_frames_follows_currentpage_nav(tmp_path):
    from PIL import Image

    from vadana import video as vid
    from vadana.whiteboard import Shape, Whiteboard

    def pencil(page, t):
        return (t, page, f"s{t}", Shape("pencil", 1, t, pts=[(100.0, 100.0), (200.0, 200.0)]))

    # prof flips to page 1 at 5s (just talks), and only draws on it at 30s
    events = [pencil((0, 0), 1000), pencil((0, 1), 30000)]
    nav = [(1000, (0, 0)), (5000, (0, 1))]
    board = Whiteboard(final={(0, 0): {}, (0, 1): {}}, events=events, nav=nav)
    bg = {(0, 0): Image.new("RGB", (40, 30), "white"), (0, 1): Image.new("RGB", (40, 30), "white")}

    ts = [t for t, _ in vid.build_frames(board, str(tmp_path / "a"), scale=1, max_fps=2.0, backgrounds=bg)]
    assert ts == sorted(ts)                              # frames stay time-ordered
    assert any(abs(t - 5.0) < 0.6 for t in ts)           # page shows at the flip (5s), not the 30s stroke

    # no backgrounds -> stroke-driven: the page only appears when it's drawn on (30s)
    ts2 = [t for t, _ in vid.build_frames(board, str(tmp_path / "b"), scale=1, max_fps=2.0)]
    assert not any(abs(t - 5.0) < 0.6 for t in ts2)


def test_whiteboard_parse_shapes(ftcontent_xml):
    doc = wb.parse(ftcontent_xml)
    assert doc.pages == [0]
    shapes = doc.final[0]
    assert set(shapes) == {"5", "6"}
    pencil = shapes["5"]
    assert pencil.kind == "pencil"
    assert pencil.pts == [(100.0, 50.0), (300.0, 150.0)]   # box_xy + pt * box_size
    assert pencil.color == (255, 0, 0)
    text = shapes["6"]
    assert text.kind == "text"
    assert text.lines == ["hello"]
    assert text.color == (0, 0, 255)


def test_whiteboard_delete_removes_shape():
    xml = (
        '<recording><Message time="1"><String><![CDATA[set_WB_So_0]]></String>'
        '<code><![CDATA[add]]></code><name><![CDATA[9]]></name><newValue>'
        '<type><![CDATA[pencil]]></type><x><![CDATA[0]]></x><y><![CDATA[0]]></y>'
        '<width><![CDATA[10]]></width><height><![CDATA[10]]></height><depth><![CDATA[1]]></depth>'
        '<pts><x><![CDATA[0]]></x><y><![CDATA[0]]></y></pts></newValue></Message>'
        '<Message time="2"><String><![CDATA[set_WB_So_0]]></String>'
        '<code><![CDATA[delete]]></code><name><![CDATA[9]]></name><newValue></newValue></Message>'
        '</recording>'
    )
    doc = wb.parse(xml)
    assert doc.final.get(0, {}) == {}
    assert doc.pages == []


def test_smooth_densifies_and_keeps_endpoints():
    pts = [(0, 0), (10, 5), (20, 0), (30, 5)]
    out = wb._smooth(pts, steps=6)
    assert out[0] == pts[0]            # first endpoint stays put
    assert out[-1] == pts[-1]          # last endpoint stays put
    assert len(out) > len(pts)         # spline inserts intermediate samples
    assert wb._smooth([(1, 1), (2, 2)]) == [(1, 1), (2, 2)]   # <3 pts: untouched


def test_whiteboard_render_size(ftcontent_xml):
    doc = wb.parse(ftcontent_xml)
    im = wb.render_page(list(doc.final[0].values()), scale=2)
    assert im.size == (wb.NATIVE_W * 2, wb.NATIVE_H * 2)


def test_load_from_package_finds_whiteboard(package):
    doc = wb.load_from_package(package)
    assert doc.pages


def test_load_from_package_no_whiteboard():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mainstream.xml", "<r></r>")
    buf.seek(0)
    doc = wb.load_from_package(zipfile.ZipFile(buf))
    assert doc.pages == []


def test_timeline_parse_streams(indexstream_xml):
    streams = tl.parse_streams(indexstream_xml)
    assert len(streams) == 2
    assert streams[0] == {"start_ms": 35000, "name": "cameraVoip_0_3",
                          "pub": "5", "type": "cameraVoip"}
    assert streams[1]["type"] == "screenshare"
    assert streams[1]["start_ms"] == 625000


def test_timeline_parse_streams_empty():
    assert tl.parse_streams("<r></r>") == []

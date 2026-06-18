import io
import zipfile

from vadana import whiteboard as wb
from vadana import timeline as tl


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

import io
import zipfile

import pytest

MAINSTREAM = """<recording>
  <downloadUrl><![CDATA[/system/download?download-url=/_a7/77/source/&name=Chapter%201.pdf]]></downloadUrl>
  <downloadUrl><![CDATA[/system/download?download-url=/_a7/77/source/&name=notes.docx]]></downloadUrl>
  <downloadUrl><![CDATA[/system/download?download-url=/_a7/77/source/&name=Chapter%201.pdf]]></downloadUrl>
</recording>"""

FTCONTENT = """<recording>
<Message time="1000">
<String><![CDATA[set_WB_So_0]]></String>
<code><![CDATA[add]]></code><name><![CDATA[5]]></name><newValue><type><![CDATA[pencil]]></type><x><![CDATA[100]]></x><y><![CDATA[50]]></y><width><![CDATA[200]]></width><height><![CDATA[100]]></height><depth><![CDATA[1]]></depth><strokeCol><![CDATA[16711680]]></strokeCol><strokeWeight><![CDATA[3]]></strokeWeight><pts><x><![CDATA[0]]></x><y><![CDATA[0]]></y><x><![CDATA[1]]></x><y><![CDATA[1]]></y></pts></newValue>
<code><![CDATA[add]]></code><name><![CDATA[6]]></name><newValue><type><![CDATA[text]]></type><x><![CDATA[10]]></x><y><![CDATA[20]]></y><width><![CDATA[300]]></width><height><![CDATA[40]]></height><depth><![CDATA[2]]></depth><htmlText><![CDATA[<P><FONT COLOR="#0000FF" SIZE="24">hello</FONT></P>]]></htmlText></newValue>
</Message>
</recording>"""

INDEXSTREAM = """<recording>
<streamAdded><startTime><![CDATA[35000]]></startTime><streamId><![CDATA[a1]]></streamId><streamName><![CDATA[/cameraVoip_0_3]]></streamName><streamPublisherID><![CDATA[5]]></streamPublisherID><streamType><![CDATA[cameraVoip]]></streamType></streamAdded>
<streamAdded><startTime><![CDATA[625000]]></startTime><streamId><![CDATA[b2]]></streamId><streamName><![CDATA[/screenshare_2_5]]></streamName><streamPublisherID><![CDATA[27]]></streamPublisherID><streamType><![CDATA[screenshare]]></streamType></streamAdded>
</recording>"""


def build_zip(members: dict) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in members.items():
            z.writestr(name, content)
    buf.seek(0)
    return zipfile.ZipFile(buf)


class FakeResp:
    def __init__(self, content=b"%PDF-1.4\nfake", ct="application/pdf", status=200):
        self.content = content
        self.status_code = status
        self.headers = {"content-type": ct}


class FakeClient:
    """Stands in for ConnectClient: records requested URLs, returns a fixed resp."""
    def __init__(self, resp=None):
        self.requested = []
        self._resp = resp if resp is not None else FakeResp()

    def get(self, url, timeout=600, **kw):
        self.requested.append(url)
        return self._resp


@pytest.fixture
def mainstream_xml():
    return MAINSTREAM


@pytest.fixture
def ftcontent_xml():
    return FTCONTENT


@pytest.fixture
def indexstream_xml():
    return INDEXSTREAM


@pytest.fixture
def package():
    return build_zip({"mainstream.xml": MAINSTREAM,
                      "ftcontent1.xml": FTCONTENT,
                      "indexstream.xml": INDEXSTREAM})


@pytest.fixture
def fake_client():
    return FakeClient()


@pytest.fixture
def make_zip():
    return build_zip


@pytest.fixture
def make_client():
    def _make(content=b"%PDF-1.4\nfake", ct="application/pdf", status=200):
        return FakeClient(FakeResp(content=content, ct=ct, status=status))
    return _make

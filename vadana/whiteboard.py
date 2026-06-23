from __future__ import annotations

import io
import re
import html
import math
import zipfile
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

NATIVE_W, NATIVE_H = 800, 600
STROKE_WIDTH_MUL = 1.0
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf",
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\arial.ttf",
)

_MSG_RE = re.compile(r'<Message time="(\d+)"[^>]*>(.*?)</Message>', re.S)
_CHANGE_RE = re.compile(
    r"<code><!\[CDATA\[([a-z]+)\]\]></code>\s*"
    r"<name><!\[CDATA\[(\d+)\]\]></name>\s*"
    r"<newValue>(.*?)</newValue>",
    re.S,
)
_PAGE_RE = re.compile(r"<String><!\[CDATA\[set_WB_So_(\d+)\]\]>")
_PT_RE = re.compile(r"<x><!\[CDATA\[([^\]]*)\]\]></x>\s*<y><!\[CDATA\[([^\]]*)\]\]></y>")
_CURPAGE_RE = re.compile(r"<name><!\[CDATA\[currentPage\]\]></name>\s*<newValue><!\[CDATA\[(\d+)\]\]></newValue>")
_TPGNUM_RE = re.compile(r"tPgNum-(\d+)")
_PTR_CHANGE_RE = re.compile(r"<name><!\[CDATA\[([^\]]+)\]\]></name>\s*<newValue><!\[CDATA\[([^\]]*)\]\]>")

@dataclass
class Shape:
    kind: str
    depth: int
    t: int
    pts: list = field(default_factory=list)
    color: tuple = (0, 0, 0)
    width: int = 2
    x: float = 0.0
    y: float = 0.0
    lines: list = field(default_factory=list)
    size: int = 21

@dataclass
class Whiteboard:
    final: dict
    events: list
    nav: list = field(default_factory=list)

    @property
    def pages(self) -> list[int]:
        return sorted(p for p, shapes in self.final.items() if shapes)

    @property
    def duration_ms(self) -> int:
        return max((t for t, *_ in self.events), default=0)

def _num(text: str, tag: str, default: float = 0.0) -> float:
    m = re.search(r"<" + tag + r"><!\[CDATA\[([^\]]*)\]\]></" + tag + r">", text)
    try:
        return float(m.group(1)) if m else default
    except ValueError:
        return default

def _color(dec) -> tuple:
    try:
        c = int(float(dec))
    except (TypeError, ValueError):
        return (0, 0, 0)
    return ((c >> 16) & 255, (c >> 8) & 255, c & 255)

def _parse_shape(nv: str, t: int) -> Shape | None:
    tm = re.search(r"<type><!\[CDATA\[([^\]]*)\]\]>", nv)
    if not tm:
        return None
    kind = tm.group(1)
    no_pts = re.sub(r"<pts>.*?</pts>", "", nv, flags=re.S)
    bx, by = _num(no_pts, "x"), _num(no_pts, "y")
    bw, bh = _num(no_pts, "width"), _num(no_pts, "height")
    depth = int(_num(nv, "depth"))

    if kind == "pencil":
        block = re.search(r"<pts>(.*?)</pts>", nv, re.S)
        rel = _PT_RE.findall(block.group(1)) if block else []
        pts = [(bx + float(rx) * bw, by + float(ry) * bh) for rx, ry in rel]
        sc = re.search(r"<strokeCol><!\[CDATA\[([^\]]*)\]\]>", nv)
        return Shape("pencil", depth, t, pts=pts,
                     color=_color(sc.group(1)) if sc else (0, 0, 0),
                     width=max(1, min(30, int(_num(nv, "strokeWeight", 2) * 1))))
    raw_m = (re.search(r"<htmlText><!\[CDATA\[(.*?)\]\]></htmlText>", nv, re.S)
             or re.search(r"<text><!\[CDATA\[(.*?)\]\]></text>", nv, re.S))
    raw = raw_m.group(1) if raw_m else ""
    lines = [html.unescape(re.sub(r"<[^>]+>", "", ln)).rstrip()
             for ln in re.split(r"</TEXTFORMAT>|</P>", raw)
             if re.sub(r"<[^>]+>", "", ln).strip()]
    cm = re.search(r'COLOR="#([0-9A-Fa-f]{6})"', raw)
    szm = re.search(r'SIZE="(\d+)"', raw)
    return Shape("text", depth, t, x=bx, y=by, lines=lines,
                 color=tuple(int(cm.group(1)[i:i + 2], 16) for i in (0, 2, 4)) if cm else (0, 0, 0),
                 size=int(szm.group(1)) if szm else 21)

def parse(ftcontent_xml: str) -> Whiteboard:
    final: dict = {}
    events: list = []
    nav: list = []
    for t_str, body in _MSG_RE.findall(ftcontent_xml):
        cp = _CURPAGE_RE.search(body)
        if cp:
            nav.append((int(t_str), int(cp.group(1))))
        pg = _PAGE_RE.search(body)
        if not pg:
            continue
        t = int(t_str)
        page = int(pg.group(1))
        final.setdefault(page, {})
        for code, sid, nv in _CHANGE_RE.findall(body):
            if code == "delete":
                final[page].pop(sid, None)
                events.append((t, page, sid, None))
                continue
            if "<type>" not in nv:
                continue
            shape = _parse_shape(nv, t)
            if shape:
                final[page][sid] = shape
                events.append((t, page, sid, shape))
    return Whiteboard(final=final, events=events, nav=nav)

def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(p, max(8, size))
        except OSError:
            continue
    return ImageFont.load_default()

def _clamp(v: float, hi: int, scale: int):
    if not math.isfinite(v):
        return None
    return int(max(0, min(hi, v * scale)))

def _smooth(pts, steps: int = 6):
    """Catmull-Rom spline through pts -> a denser, smoother polyline so sparse
    handwriting samples read as curves instead of straight angular segments."""
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for i in range(len(pts) - 1):
        p0 = pts[i - 1] if i else pts[0]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < len(pts) else pts[-1]
        for j in range(1, steps + 1):
            t = j / steps
            t2, t3 = t * t, t * t * t
            x = 0.5 * (2*p1[0] + (p2[0]-p0[0])*t + (2*p0[0]-5*p1[0]+4*p2[0]-p3[0])*t2 + (3*p1[0]-p0[0]-3*p2[0]+p3[0])*t3)
            y = 0.5 * (2*p1[1] + (p2[1]-p0[1])*t + (2*p0[1]-5*p1[1]+4*p2[1]-p3[1])*t2 + (3*p1[1]-p0[1]-3*p2[1]+p3[1])*t3)
            out.append((round(x), round(y)))
    return out

def draw_shape(dr: ImageDraw.ImageDraw, s: Shape, scale: int, W: int, H: int) -> None:
    """Draw a single shape onto an existing canvas (used by both still and video)."""
    if s.kind == "pencil" and s.pts:
        pts = []
        for nx, ny in s.pts:
            cx, cy = _clamp(nx, W, scale), _clamp(ny, H, scale)
            if cx is None or cy is None:
                continue
            if not pts or pts[-1] != (cx, cy):
                pts.append((cx, cy))
        w = max(2, int(round(s.width * scale * STROKE_WIDTH_MUL)))
        r = max(1, w // 2)
        if len(pts) == 1:
            x, y = pts[0]
            dr.ellipse([x - r, y - r, x + r, y + r], fill=s.color)
        else:
            dr.line(_smooth(pts), fill=s.color, width=w, joint="curve")
            for x, y in (pts[0], pts[-1]):
                dr.ellipse([x - r, y - r, x + r, y + r], fill=s.color)
    elif s.kind == "text":
        x0, y0 = _clamp(s.x, W, scale), _clamp(s.y, H, scale)
        if x0 is None or y0 is None:
            return
        fnt = _font(int(s.size * scale * 1.05))
        lh = int(s.size * scale * 1.3)
        y = y0
        for ln in s.lines:
            try:
                dr.text((x0, y), ln, fill=s.color, font=fnt)
            except Exception:
                pass
            y += lh

def render_page(shapes, scale: int = 2, label: str | None = None, ss: int = 2,
                bg: Image.Image | None = None) -> Image.Image:
    """Render one page. Supersampled (ss x) then downscaled -> anti-aliased strokes.
    bg: the shared-PDF page image to draw the strokes over (the professor annotated
    it); None -> a white board."""
    W, H = NATIVE_W * scale, NATIVE_H * scale
    aspect = None
    if bg is not None:
        aspect = bg.width / bg.height
        im = bg.convert("RGB").resize((W * ss, H * ss), Image.LANCZOS)
    else:
        im = Image.new("RGB", (W * ss, H * ss), "white")
    dr = ImageDraw.Draw(im)
    for s in sorted(shapes, key=lambda s: s.depth):
        draw_shape(dr, s, scale * ss, W * ss, H * ss)
    if ss != 1:
        im = im.resize((W, H), Image.LANCZOS)
    if aspect:
        im = im.resize((round(H * aspect), H), Image.LANCZOS)
    if label:
        ImageDraw.Draw(im).text((8, 8), label, fill=(210, 210, 210), font=_font(20))
    return im

def render_final_pages(wb: Whiteboard, scale: int = 2, backgrounds: dict | None = None,
                       ss: int = 3) -> list[Image.Image]:
    backgrounds = backgrounds or {}
    return [render_page(list(wb.final[p].values()), scale, f"page {i + 1}", ss=ss, bg=backgrounds.get(p))
            for i, p in enumerate(wb.pages)]

def pdf_backgrounds(pdf_paths, page_keys) -> dict:
    """Map whiteboard page keys 1:1 onto the pages of whichever shared PDF has the
    same page count (the document the professor annotated). {} if none matches, so
    the caller falls back to a white board.

    ponytail: 1:1 page-count match only. A lecture that flips between several PDFs
    or annotates a subset would need the share-pod page-change events — add that if
    it actually comes up."""
    if not pdf_paths or not page_keys:
        return {}
    try:
        import fitz
    except ImportError:
        return {}
    for p in pdf_paths:
        try:
            doc = fitz.open(p)
        except Exception:
            continue
        try:
            if doc.page_count == len(page_keys):
                out = {}
                for i, key in enumerate(page_keys):
                    pix = doc[i].get_pixmap(matrix=fitz.Matrix(2, 2))
                    out[key] = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                return out
        finally:
            doc.close()
    return {}

def save_pdf(images: list[Image.Image], path: str) -> None:
    """PDF without relying on Pillow's JPEG codec (uses img2pdf over PNG bytes)."""
    import img2pdf
    png_bytes = []
    for im in images:
        buf = io.BytesIO()
        im.save(buf, "PNG")
        png_bytes.append(buf.getvalue())
    with open(path, "wb") as f:
        f.write(img2pdf.convert(png_bytes))

def load_from_package(zf: zipfile.ZipFile) -> Whiteboard:
    """Scan every ftcontent<N>.xml pod and merge their whiteboard content — a
    recording's whiteboard may live in ftcontent3 (not ftcontent1)."""
    fts = sorted(n for n in zf.namelist() if re.fullmatch(r"ftcontent\d+\.xml", n))
    merged_final: dict = {}
    merged_events: list = []
    merged_nav: list = []
    for fidx, name in enumerate(fts):
        xml = zf.read(name).decode("utf-8", "replace")
        if "set_WB_So" not in xml:
            continue
        wb = parse(xml)
        for page, shapes in wb.final.items():
            if shapes:
                merged_final[(fidx, page)] = shapes
        for t, page, sid, shape in wb.events:
            merged_events.append((t, (fidx, page), sid, shape))
        for t, page in wb.nav:
            merged_nav.append((t, (fidx, page)))
    merged_events.sort(key=lambda e: e[0])
    merged_nav.sort(key=lambda e: e[0])
    return Whiteboard(final=merged_final, events=merged_events, nav=merged_nav)

def load_pdf_content(zf: zipfile.ZipFile) -> list[tuple[int, int]]:
    """Page-show timeline for an Adobe "Share PDF" pod (setPdfContentSo events):
    [(time_ms, page_index0), ...] — the 0-based PDF page anchored at the top of the
    viewport (`tPgNum`) over time. Empty if the recording has no shared-PDF pod.
    Lets the video show a shared document, not just whiteboard/screen-share."""
    nav: list[tuple[int, int]] = []
    for name in sorted(n for n in zf.namelist() if re.fullmatch(r"ftcontent\d+\.xml", n)):
        xml = zf.read(name).decode("utf-8", "replace")
        if "pdfContent" not in xml:
            continue
        for t_str, body in _MSG_RE.findall(xml):
            m = _TPGNUM_RE.search(body)
            if m:
                nav.append((int(t_str), int(m.group(1))))
    nav.sort()
    return nav

def load_pointer(zf: zipfile.ZipFile) -> list[tuple[int, float, float, bool]]:
    """Laser-pointer track for a Share pod (setPointerSo): [(time_ms, x, y, visible)]
    with x,y as 0-100 percent of the shared page. The presenter's pointer, rendered
    as a moving dot over the document."""
    out: list[tuple[int, float, float, bool]] = []
    x = y = 50.0
    vis = False
    for name in sorted(n for n in zf.namelist() if re.fullmatch(r"ftcontent\d+\.xml", n)):
        xml = zf.read(name).decode("utf-8", "replace")
        if "setPointerSo" not in xml:
            continue
        for t_str, body in _MSG_RE.findall(xml):
            if "setPointerSo" not in body:
                continue
            touched = False
            for nm, nv in _PTR_CHANGE_RE.findall(body):
                try:
                    if nm == "x" and nv:
                        x, touched = float(nv), True
                    elif nm == "y" and nv:
                        y, touched = float(nv), True
                    elif nm == "visible":
                        vis, touched = (nv == "true"), True
                except ValueError:
                    pass
            if touched:
                out.append((int(t_str), x, y, vis))
    out.sort()
    return out

def make_pdf(zf: zipfile.ZipFile, out_path: str, scale: int = 6,
             thumb_path: str | None = None, pdf_paths=None) -> str | None:
    """Render the whiteboard's final pages to a PDF (high-res raster, scale 6 / 3x
    supersample). None if no whiteboard content. If thumb_path is given, the first page
    is also written there as a small JPEG (Telegram thumbnail: <=320px). pdf_paths:
    shared PDFs to use as page backgrounds when the professor annotated a document
    (page-count must match the board)."""
    wb = load_from_package(zf)
    if not wb.pages:
        return None
    imgs = render_final_pages(wb, scale, pdf_backgrounds(pdf_paths, wb.pages))
    save_pdf(imgs, out_path)
    if thumb_path and imgs:
        th = imgs[0].convert("RGB")
        th.thumbnail((320, 320))
        th.save(thumb_path, "JPEG", quality=80)
    return out_path

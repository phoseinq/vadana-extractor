"""
Part 2a — parse and render the Adobe Connect whiteboard.

A whiteboard lecture has no rendered video; the board is stored in
ftcontent1.xml as timed vector events on per-page SharedObjects
(`set_WB_So_<page>`). Each shape is `pencil` (a stroke) or `text`.

Coordinate model (reverse-engineered):
  * every shape has a bounding box x,y,width,height in NATIVE px (800x600)
  * a stroke's <pts> are normalized 0..1 RELATIVE to that box:
        native_x = box_x + pt_x * box_width
"""
from __future__ import annotations

import io
import re
import html
import math
import zipfile
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

NATIVE_W, NATIVE_H = 800, 600
# Typed-text shapes (e.g. pasted code) need a real scalable TTF. The server is
# Linux, so list its fonts FIRST — otherwise _font() fell back to Pillow's tiny
# bitmap default and the code was effectively invisible. Monospace fits code best.
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


@dataclass
class Shape:
    kind: str            # 'pencil' | 'text'
    depth: int
    t: int               # event time (ms from recording start)
    pts: list = field(default_factory=list)   # absolute native-px points (pencil)
    color: tuple = (0, 0, 0)
    width: int = 2
    x: float = 0.0       # text anchor (native px)
    y: float = 0.0
    lines: list = field(default_factory=list)
    size: int = 21


@dataclass
class Whiteboard:
    final: dict          # page -> {shape_id: Shape}  (last state)
    events: list         # ordered (t, page, shape_id, Shape|None)  None = delete

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
    # text
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
    for t_str, body in _MSG_RE.findall(ftcontent_xml):
        pg = _PAGE_RE.search(body)
        if not pg:
            continue
        t = int(t_str)
        page = int(pg.group(1))
        final.setdefault(page, {})
        for code, sid, nv in _CHANGE_RE.findall(body):
            if code == "delete":                     # professor erased this shape
                final[page].pop(sid, None)
                events.append((t, page, sid, None))
                continue
            if "<type>" not in nv:
                continue
            shape = _parse_shape(nv, t)
            if shape:
                final[page][sid] = shape
                events.append((t, page, sid, shape))
    return Whiteboard(final=final, events=events)


# ----------------------------------------------------------------------------- rendering

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
        w = max(2, int(round(s.width * scale * 1.4)))
        r = max(1, w // 2)
        if len(pts) == 1:
            x, y = pts[0]
            dr.ellipse([x - r, y - r, x + r, y + r], fill=s.color)
        else:
            for a, b in zip(pts, pts[1:]):
                dr.line([a, b], fill=s.color, width=w)
            for x, y in pts:                        # round caps/joins -> smoother strokes
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


def render_page(shapes, scale: int = 2, label: str | None = None, ss: int = 2) -> Image.Image:
    """Render one page. Supersampled (ss x) then downscaled -> anti-aliased strokes."""
    W, H = NATIVE_W * scale, NATIVE_H * scale
    im = Image.new("RGB", (W * ss, H * ss), "white")
    dr = ImageDraw.Draw(im)
    for s in sorted(shapes, key=lambda s: s.depth):
        draw_shape(dr, s, scale * ss, W * ss, H * ss)
    if ss != 1:
        im = im.resize((W, H), Image.LANCZOS)
    if label:
        ImageDraw.Draw(im).text((8, 8), label, fill=(210, 210, 210), font=_font(20))
    return im


def render_final_pages(wb: Whiteboard, scale: int = 2) -> list[Image.Image]:
    return [render_page(list(wb.final[p].values()), scale, f"page {i + 1}")
            for i, p in enumerate(wb.pages)]


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
    merged_events.sort(key=lambda e: e[0])
    return Whiteboard(final=merged_final, events=merged_events)


def make_pdf(zf: zipfile.ZipFile, out_path: str, scale: int = 2) -> str | None:
    """Render the whiteboard's final pages to a PDF. None if no whiteboard content."""
    wb = load_from_package(zf)
    if not wb.pages:
        return None
    save_pdf(render_final_pages(wb, scale), out_path)
    return out_path

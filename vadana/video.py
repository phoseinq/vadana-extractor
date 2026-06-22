from __future__ import annotations

import os
import re
import subprocess

from PIL import Image, ImageDraw

from . import whiteboard as wb_mod
from .whiteboard import Whiteboard, NATIVE_W, NATIVE_H

DENOISE_AF = os.environ.get("AUDIO_DENOISE", "highpass=f=85,afftdn=nr=12:nf=-25,dynaudnorm=f=200:g=6")

def _blank(scale):
    return Image.new("RGB", (NATIVE_W * scale, NATIVE_H * scale), "white")

def _clean_nav(nav, min_show_ms=500):
    """Drop page flips that flashed past for under min_show_ms (rapid back-and-forth)
    so the video doesn't flicker; keep the page the prof actually settled on."""
    nav = sorted(set(nav))
    out = []
    for i, (t, p) in enumerate(nav):
        nxt = nav[i + 1][0] if i + 1 < len(nav) else 1 << 62
        if nxt - t >= min_show_ms:
            out.append((t, p))
    return out or nav[-1:]

def build_frames(wb: Whiteboard, frames_dir: str, scale: int = 2,
                 max_fps: float = 4.0, progress=None, backgrounds=None) -> list[tuple[float, str]]:
    """Render timed frames. Returns [(start_seconds, png_path), ...] in order.

    backgrounds: {page_key: PIL image} of the shared PDF page the strokes sit on
    (annotated-document recordings); a page with no background stays white.
    progress(done, total) is called as events are processed (for a progress bar)."""
    os.makedirs(frames_dir, exist_ok=True)
    W, H = NATIVE_W * scale, NATIVE_H * scale
    interval = 1000.0 / max_fps
    backgrounds = backgrounds or {}

    def fresh(page):
        bg = backgrounds.get(page)
        return bg.convert("RGB").resize((W, H), Image.LANCZOS) if bg is not None else _blank(scale)

    page_canvas: dict[int, Image.Image] = {}
    page_shapes: dict[int, dict] = {}
    page_draw: dict[int, ImageDraw.ImageDraw] = {}

    def ensure(page):
        if page not in page_canvas:
            page_canvas[page] = fresh(page)
            page_draw[page] = ImageDraw.Draw(page_canvas[page])
            page_shapes[page] = {}

    def repaint(page):
        page_canvas[page] = fresh(page)
        page_draw[page] = ImageDraw.Draw(page_canvas[page])
        for s in sorted(page_shapes[page].values(), key=lambda s: s.depth):
            wb_mod.draw_shape(page_draw[page], s, scale, W, H)

    frames: list[tuple[float, str]] = []
    idx = 0

    def emit(t_ms, page):
        nonlocal idx
        path = os.path.join(frames_dir, f"f{idx:06d}.png")
        page_canvas[page].copy().save(path)
        frames.append((t_ms / 1000.0, path))
        idx += 1

    last_emit = -1e9
    nav = _clean_nav(getattr(wb, "nav", None) or [])

    if nav:
        stream = ([(t, 0, ("show", p)) for (t, p) in nav]
                  + [(t, 1, ("draw", pg, sid, sh)) for (t, pg, sid, sh) in wb.events])
        stream.sort(key=lambda e: (e[0], e[1]))
        total = len(stream) or 1
        displayed = None
        for ev_i, (t, _, pl) in enumerate(stream, 1):
            if pl[0] == "show":
                page = pl[1]
                ensure(page)
                if page != displayed:
                    displayed = page
                    emit(t, page)
                    last_emit = t
            else:
                _, page, sid, shape = pl
                ensure(page)
                if shape is None:
                    page_shapes[page].pop(sid, None)
                    repaint(page)
                else:
                    page_shapes[page][sid] = shape
                    wb_mod.draw_shape(page_draw[page], shape, scale, W, H)
                if page == displayed and t - last_emit >= interval:
                    emit(t, page)
                    last_emit = t
            if progress and ev_i % 15 == 0:
                progress(ev_i, total)
        if displayed is not None and (not frames or frames[-1][0] < wb.duration_ms / 1000.0):
            emit(wb.duration_ms, displayed)
        return frames

    current_page = None
    total_ev = len(wb.events) or 1
    for ev_i, (t, page, sid, shape) in enumerate(wb.events, 1):
        ensure(page)
        if shape is None:
            page_shapes[page].pop(sid, None)
            repaint(page)
        else:
            page_shapes[page][sid] = shape
            wb_mod.draw_shape(page_draw[page], shape, scale, W, H)
        current_page = page
        if t - last_emit >= interval:
            emit(t, page)
            last_emit = t
        if progress and ev_i % 15 == 0:
            progress(ev_i, total_ev)
    if current_page is not None and (not frames or frames[-1][0] < wb.duration_ms / 1000.0):
        emit(wb.duration_ms, current_page)
    return frames

def _concat_file(frames, list_path, tail_seconds=3.0):
    """ffmpeg concat demuxer list with per-frame durations."""
    lines = []
    for i, (start, path) in enumerate(frames):
        end = frames[i + 1][0] if i + 1 < len(frames) else start + tail_seconds
        dur = max(0.04, end - start)
        lines.append(f"file '{os.path.abspath(path).replace(chr(92), '/')}'")
        lines.append(f"duration {dur:.3f}")
    lines.append(f"file '{os.path.abspath(frames[-1][1]).replace(chr(92), '/')}'")
    with open(list_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def pdf_frames(pdf_paths, frames_dir, canvas=(1280, 960)):
    """Render every page of the PDFs onto a uniform white canvas. Returns png paths."""
    import fitz
    from PIL import Image
    os.makedirs(frames_dir, exist_ok=True)
    W, H = canvas
    out, k = [], 0
    for pdf in pdf_paths:
        doc = fitz.open(pdf)
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            img.thumbnail((W, H))
            sheet = Image.new("RGB", (W, H), "white")
            sheet.paste(img, ((W - img.width) // 2, (H - img.height) // 2))
            p = os.path.join(frames_dir, f"s{k:05d}.png")
            sheet.save(p)
            out.append(p)
            k += 1
        doc.close()
    return out

def make_media_video(zf, work_dir, out_path, pdf_paths=None, scale: int = 2, progress=None):
    """Archive video for non-whiteboard recordings: a slideshow of the shared
    PDFs (if any) or a single blank page — both over the lecture audio."""
    from . import audio as audio_mod
    from PIL import Image

    def rep(stage, pct):
        if progress:
            progress(stage, pct)

    os.makedirs(work_dir, exist_ok=True)
    rep("audio", 25)
    audio_path = audio_mod.extract_audio(zf, work_dir, os.path.join(work_dir, "audio.m4a"),
                                         progress=lambda fr: rep("audio", 25 + fr * 28))
    dur = audio_mod.duration_seconds(audio_path) if audio_path else 0.0

    rep("render", 55)
    pages = pdf_frames(pdf_paths, os.path.join(work_dir, "slides")) if pdf_paths else []
    if not pages:
        blank = os.path.join(work_dir, "blank.png")
        Image.new("RGB", (1280, 960), "white").save(blank)
        pages = [blank]

    per = max(2.0, dur / len(pages)) if dur else 4.0
    frames = [(i * per, p) for i, p in enumerate(pages)]
    rep("encode", 82)
    mux(frames, audio_path, out_path, work_dir, audio_skip_seconds=0.0,
        progress=lambda fr: rep("encode", 82 + fr * 16), out_fps=2)
    rep("done", 100)
    return out_path

def _meta_seconds(zf, xml_name) -> float:
    try:
        d = zf.read(xml_name).decode("utf-8", "replace")
    except KeyError:
        return 0.0
    m = re.search(r"onMetaData.*?<Number><!\[CDATA\[([\d.]+)\]\]>", d, re.S)
    return float(m.group(1)) if m else 0.0

def make_full_video(zf, work_dir, out_path, scale: int = 2, max_fps: float = 4.0, progress=None,
                    pdf_paths=None):
    """Mixed recording -> one 16:9 MP4 on the master timeline: the whiteboard
    (full length, rendered big then fitted so the handwriting is anti-aliased and
    legible) with the shared screen shown full-frame during its periods, and audio
    placed at real offsets (gaps in the source mic = silence). None if neither.

    pdf_paths: shared PDFs; if one matches the board's page count, the strokes are
    drawn over its pages (the professor annotated a document, not a blank board)."""
    from . import whiteboard as wb_mod
    from . import timeline as tl
    from PIL import Image

    def rep(stage, pct):
        if progress:
            progress(stage, pct)

    os.makedirs(work_dir, exist_ok=True)
    streams = tl.parse_streams(zf.read("indexstream.xml").decode("utf-8", "replace"))
    shares = [s for s in streams if s["type"] == "screenshare"]
    wb = wb_mod.load_from_package(zf)
    if not wb.pages and not shares:
        return None

    master_s = max(_meta_seconds(zf, "mainstream.xml"), _meta_seconds(zf, "ftcontent1.xml"),
                   wb.duration_ms / 1000.0)
    OUT_W, OUT_H = 1920, 1080
    RENDER_SCALE = 3

    rep("audio", 10)
    audio_path = tl.build_master_audio(zf, streams, work_dir, os.path.join(work_dir, "master.m4a"))

    rep("render", 22)
    wb_frames = []
    if wb.pages:
        backgrounds = wb_mod.pdf_backgrounds(pdf_paths, wb.pages)
        content_aspect = None
        if backgrounds:
            b0 = next(iter(backgrounds.values()))
            content_aspect = b0.width / b0.height
        raw = build_frames(wb, os.path.join(work_dir, "frames"), scale=RENDER_SCALE, max_fps=max_fps,
                           progress=lambda i, n: rep("render", 22 + int(28 * i / max(1, n))),
                           backgrounds=backgrounds)
        sheet_dir = os.path.join(work_dir, "wb16")
        os.makedirs(sheet_dir, exist_ok=True)
        nraw = len(raw) or 1
        for i, (t, p) in enumerate(raw):
            im = Image.open(p).convert("RGB")
            if content_aspect:
                im = im.resize((round(im.height * content_aspect), im.height), Image.LANCZOS)
            im.thumbnail((OUT_W, OUT_H), Image.LANCZOS)
            sheet = Image.new("RGB", (OUT_W, OUT_H), "white")
            sheet.paste(im, ((OUT_W - im.width) // 2, (OUT_H - im.height) // 2))
            fp = os.path.join(sheet_dir, f"{i:06d}.png")
            sheet.save(fp)
            wb_frames.append((t, fp))
            if i % 8 == 0:
                rep("render", 50 + int(10 * i / nraw))

    rep("render", 62)
    ss_dir = os.path.join(work_dir, "ss")
    os.makedirs(ss_dir, exist_ok=True)
    windows, ss_frames = [], []
    for si, s in enumerate(shares):
        rep("render", 62 + int(14 * si / max(1, len(shares))))
        flv = s["name"] + ".flv"
        try:
            data = zf.read(flv)
        except KeyError:
            continue
        p = os.path.join(work_dir, os.path.basename(flv))
        with open(p, "wb") as f:
            f.write(data)
        start = s["start_ms"] / 1000.0
        dur = _meta_seconds(zf, s["name"] + ".xml") or 60.0
        windows.append((start, start + dur))
        pat = os.path.join(ss_dir, f"{si}_%05d.png")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", p, "-vf",
                        f"fps=1,scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
                        f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2:color=black", pat], check=True)
        k = 0
        while os.path.exists(os.path.join(ss_dir, f"{si}_{k + 1:05d}.png")):
            ss_frames.append((start + k, os.path.join(ss_dir, f"{si}_{k + 1:05d}.png")))
            k += 1

    def in_share(t):
        return any(a <= t < b for a, b in windows)

    frames = [(t, p) for (t, p) in wb_frames if not in_share(t)] + ss_frames
    blank = os.path.join(work_dir, "blank0.png")
    Image.new("RGB", (OUT_W, OUT_H), "white").save(blank)
    if not frames or min(t for t, _ in frames) > 0.3:
        frames.append((0.0, blank))
    frames.sort(key=lambda f: f[0])

    rep("encode", 76)
    _mux_timed(frames, audio_path, out_path, work_dir, master_s,
               progress=lambda fr: rep("encode", 76 + fr * 23))
    rep("done", 100)
    return out_path

def _mux_timed(frames, audio_path, out_path, workdir, master_s, progress=None):
    list_path = os.path.join(workdir, "frames.txt")
    _concat_file(frames, list_path, tail_seconds=max(1.0, master_s - frames[-1][0]))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
           "-f", "concat", "-safe", "0", "-i", list_path]
    if audio_path:
        cmd += ["-i", audio_path]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "26",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-r", "4", "-movflags", "+faststart",
            "-t", f"{master_s:.3f}"]
    if audio_path:
        cmd += ["-c:a", "aac", "-b:a", "96k"]
        if DENOISE_AF:
            cmd += ["-af", DENOISE_AF]
    cmd += [out_path]
    with open(os.path.join(workdir, "ffmpeg.err"), "w") as errf:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf, text=True)
        for line in proc.stdout:
            if progress and line.startswith(("out_time_us=", "out_time_ms=")):
                try:
                    v = int(line.strip().split("=", 1)[1])
                    secs = v / (1e6 if "us=" in line else 1e3)
                    progress(max(0.0, min(1.0, secs / master_s)))
                except Exception:
                    pass
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg timed mux failed (code {proc.returncode})")
    return out_path

def mux(frames, audio_path, out_path, workdir, audio_skip_seconds=0.0, audio_offset_ms=0,
        progress=None, out_fps=None):
    """Combine timed frames + audio into an MP4.

    The video starts at the first whiteboard event (recording time t0), so the
    audio is trimmed by t0 (`audio_skip_seconds`) to stay in sync. `progress(frac)`
    is called with 0..1 while ffmpeg encodes (parsed from ffmpeg -progress).
    """
    list_path = os.path.join(workdir, "frames.txt")
    _concat_file(frames, list_path)
    total_dur = max(0.1, frames[-1][0] - frames[0][0] + 3.0)

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
           "-f", "concat", "-safe", "0", "-i", list_path]
    if audio_path:
        if audio_skip_seconds > 0:
            cmd += ["-ss", f"{audio_skip_seconds:.3f}"]
        if audio_offset_ms:
            cmd += ["-itsoffset", f"{audio_offset_ms/1000.0:.3f}"]
        cmd += ["-i", audio_path]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "26",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-movflags", "+faststart"]
    if out_fps:
        cmd += ["-r", str(out_fps)]
    if audio_path:
        cmd += ["-c:a", "aac", "-b:a", "96k", "-shortest"]
        if DENOISE_AF:
            cmd += ["-af", DENOISE_AF]
    cmd += [out_path]

    with open(os.path.join(workdir, "ffmpeg.err"), "w") as errf:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf, text=True)
        for line in proc.stdout:
            if progress and line.startswith(("out_time_us=", "out_time_ms=")):
                try:
                    val = int(line.strip().split("=", 1)[1])
                    secs = val / (1e6 if "us=" in line else 1e3)
                    progress(max(0.0, min(1.0, secs / total_dur)))
                except Exception:
                    pass
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (code {proc.returncode})")
    return out_path

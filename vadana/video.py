from __future__ import annotations

import os
import re
import subprocess

from PIL import Image, ImageDraw

from . import whiteboard as wb_mod
from .whiteboard import Whiteboard, NATIVE_W, NATIVE_H

DENOISE_AF = os.environ.get("AUDIO_DENOISE", "highpass=f=85,afftdn=nr=12:nf=-25,dynaudnorm=f=200:g=6")

def _render_workers() -> int:
    """How many processes to render frames with. RENDER_WORKERS env overrides; else
    auto: the CPU count on a strong box (>=4 cores), otherwise 1 — so small machines
    stay light and sequential, powerful ones build in parallel."""
    v = os.environ.get("RENDER_WORKERS")
    if v:
        try:
            return max(1, int(v))
        except ValueError:
            pass
    n = os.cpu_count() or 1
    return n if n >= 4 else 1

RENDER_WORKERS = _render_workers()

def _pmap(func, items, workers):
    """Map func over items in a process pool when workers>1, else sequentially. Falls
    back to sequential on any pool error, so a constrained box never breaks."""
    if workers <= 1 or len(items) < 2:
        return [func(x) for x in items]
    try:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(func, items, chunksize=max(1, len(items) // (workers * 4))))
    except Exception:
        return [func(x) for x in items]

def _wb16_fit(job):
    """Fit one rendered whiteboard frame onto the 16:9 output canvas (pool worker).
    One LANCZOS resize from the supersampled source straight to the fitted box, so
    diagonal and curved strokes stay anti-aliased; the old stretch-then-shrink path
    spent most of the supersampling on the horizontal stretch and left the writing
    stair-stepped."""
    p, out, content_aspect, ow, oh = job
    im = Image.open(p).convert("RGB")
    a = content_aspect or (im.width / im.height)
    if a >= ow / oh:
        fw, fh = ow, max(1, round(ow / a))
    else:
        fw, fh = max(1, round(oh * a)), oh
    im = im.resize((fw, fh), Image.LANCZOS)
    sheet = Image.new("RGB", (ow, oh), "white")
    sheet.paste(im, ((ow - fw) // 2, (oh - fh) // 2))
    sheet.save(out)
    return out

def _pdf_overlay(job):
    """Render one shared-PDF frame: the cached base page plus the laser dot (pool worker)."""
    base_png, out, ptr, geom = job
    im = Image.open(base_png).convert("RGB")
    if ptr:
        from PIL import ImageDraw
        ox, oy, pw, ph = geom
        px = ox + max(0.0, min(1.0, ptr[0] / 100.0)) * pw
        py = oy + max(0.0, min(1.0, ptr[1] / 100.0)) * ph
        r = max(7, im.width // 150)
        dr = ImageDraw.Draw(im, "RGBA")
        dr.ellipse([px - 2 * r, py - 2 * r, px + 2 * r, py + 2 * r], fill=(255, 45, 45, 70))
        dr.ellipse([px - r, py - r, px + r, py + r], fill=(220, 0, 0, 235))
    im.save(out)
    return out

_ENCODER = None

def _detect_encoder() -> str:
    """Pick an H.264 encoder: a working GPU one (NVENC/QSV/AMF) when the machine has
    it, else CPU libx264. VIDEO_ENCODER env forces a choice. With a GPU encoder the
    video is encoded on the GPU while the CPU handles the audio denoise in the same
    ffmpeg run — the two overlap."""
    forced = os.environ.get("VIDEO_ENCODER")
    if forced:
        return forced
    for enc in ("h264_nvenc", "h264_qsv", "h264_amf"):
        try:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                 "-i", "color=c=black:s=256x256:d=0.1", "-c:v", enc, "-f", "null", "-"],
                capture_output=True, timeout=25)
            if r.returncode == 0:
                return enc
        except Exception:
            pass
    return "libx264"

def _encoder() -> str:
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = _detect_encoder()
    return _ENCODER

def _vcodec_args() -> list:
    """ffmpeg -c:v args for the chosen encoder, tuned for near-x264 quality (text stays
    crisp). GPU encoders fall back to libx264 if absent."""
    enc = _encoder()
    if enc == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "23", "-b:v", "0", "-profile:v", "high"]
    if enc == "h264_qsv":
        return ["-c:v", "h264_qsv", "-global_quality", "23", "-preset", "medium"]
    if enc == "h264_amf":
        return ["-c:v", "h264_amf", "-rc", "cqp", "-qp_i", "22", "-qp_p", "22", "-quality", "quality"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26"]

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
    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(max_workers=RENDER_WORKERS) if RENDER_WORKERS > 1 else None
    pending: list = []

    def emit(t_ms, page):
        nonlocal idx
        path = os.path.join(frames_dir, f"f{idx:06d}.png")
        snap = page_canvas[page].copy()
        if pool is None:
            snap.save(path)
        else:
            if len(pending) >= 2 * RENDER_WORKERS:
                pending.pop(0).result()
            pending.append(pool.submit(snap.save, path))
        frames.append((t_ms / 1000.0, path))
        idx += 1

    def _drain():
        for f in pending:
            f.result()
        pending.clear()

    last_emit = -1e9
    nav = _clean_nav(getattr(wb, "nav", None) or [])

    try:
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
    finally:
        _drain()
        if pool is not None:
            pool.shutdown()

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

def _pdf_page_changes(nav, min_show_ms=800):
    """Collapse a noisy tPgNum stream to page-change points, dropping a page that
    flashed past (rapid scroll) for under min_show_ms."""
    changes, last = [], None
    for t, p in sorted(nav):
        if p != last:
            changes.append((t, p)); last = p
    out = []
    for i, (t, p) in enumerate(changes):
        nxt = changes[i + 1][0] if i + 1 < len(changes) else 1 << 62
        if nxt - t >= min_show_ms:
            out.append((t, p))
    return out or changes[-1:]

def pdf_content_frames(pdf_paths, nav, pointer, frames_dir, out_w, out_h):
    """Frames for an Adobe "Share PDF" pod: render the shared PDF's pages and overlay
    the presenter's laser pointer (a moving dot) where they pointed. Emits a frame at
    each page-change and pointer move. Returns (frames, window) — window is the
    (start_s, end_s) the document occupied on the timeline."""
    import fitz
    os.makedirs(frames_dir, exist_ok=True)
    pages_dir = os.path.join(frames_dir, "pages")
    os.makedirs(pages_dir, exist_ok=True)
    max_page = max((p for _, p in nav), default=0)
    cands = []
    for p in dict.fromkeys(pdf_paths or []):
        try:
            cands.append((fitz.open(p).page_count, p))
        except Exception:
            pass
    fit = [c for c in cands if c[0] > max_page]
    pick = min(fit)[1] if fit else (max(cands)[1] if cands else None)
    if not pick:
        return [], None
    doc = fitz.open(pick)
    base: dict[int, tuple] = {}

    def base_of(i):
        i = max(0, min(doc.page_count - 1, i))
        if i not in base:
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(2, 2))
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            im.thumbnail((out_w, out_h), Image.LANCZOS)
            sheet = Image.new("RGB", (out_w, out_h), "white")
            ox, oy = (out_w - im.width) // 2, (out_h - im.height) // 2
            sheet.paste(im, (ox, oy))
            bp = os.path.join(pages_dir, f"b{i:04d}.png")
            sheet.save(bp)
            base[i] = (bp, (ox, oy, im.width, im.height))
        return base[i]

    pchanges = _pdf_page_changes(nav)
    events = ([(t, 0, p) for t, p in pchanges]
              + [(t, 1, (x, y, v)) for t, x, y, v in pointer])
    events.sort(key=lambda e: (e[0], e[1]))
    cur_page = pchanges[0][1] if pchanges else 0
    cur_ptr = None
    jobs, times = [], []
    for t, kind, val in events:
        if kind == 0:
            cur_page = val
        else:
            cur_ptr = val
        bp, geom = base_of(cur_page)
        ptr = (cur_ptr[0], cur_ptr[1]) if (cur_ptr and cur_ptr[2]) else None
        jobs.append((bp, os.path.join(frames_dir, f"f{len(jobs):05d}.png"), ptr, geom))
        times.append(t / 1000.0)
    doc.close()
    outs = _pmap(_pdf_overlay, jobs, RENDER_WORKERS)
    frames = list(zip(times, outs))
    window = (nav[0][0] / 1000.0, nav[-1][0] / 1000.0)
    return frames, window

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
    # hold the last page to the audio end, else mux's -shortest truncates the whole
    # video to the final frame's ~3s tail and throws away the rest of the lecture audio
    if dur and frames[-1][0] < dur:
        frames.append((dur, pages[-1]))
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
                    pdf_paths=None, out_w: int = 2560, out_h: int = 1440):
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
    pdf_nav = wb_mod.load_pdf_content(zf)
    if not wb.pages and not shares and not (pdf_nav and pdf_paths):
        return None

    master_s = max(_meta_seconds(zf, "mainstream.xml"), _meta_seconds(zf, "ftcontent1.xml"),
                   wb.duration_ms / 1000.0)
    OUT_W, OUT_H = out_w, out_h
    RENDER_SCALE = 4

    rep("audio", 10)
    audio_path = tl.build_master_audio(zf, streams, work_dir, os.path.join(work_dir, "master.m4a"))

    rep("render", 22)
    wb_frames = []
    if wb.pages:
        # the whiteboard's own page-flip list is sparse (only moments the prof drew);
        # the shared document's currentPage timeline is far richer and starts earlier.
        # Drive the on-screen page from it so every page the prof showed appears (no
        # blank start, no stuck page), with the strokes drawn on the right page.
        if pdf_nav and pdf_paths:
            fidx = wb.pages[0][0] if isinstance(wb.pages[0], tuple) else 0
            nav = [(t, (fidx, p)) for t, p in pdf_nav]
            if nav and nav[0][0] > 0:
                nav.insert(0, (0, nav[0][1]))   # doc is on screen from the start; show its first page from t=0
            wb.nav = nav
        view_keys = sorted(set(wb.pages) | {pk for _, pk in wb.nav})
        backgrounds = wb_mod.pdf_backgrounds(pdf_paths, view_keys)
        content_aspect = None
        if backgrounds:
            b0 = next(iter(backgrounds.values()))
            content_aspect = b0.width / b0.height
        raw = build_frames(wb, os.path.join(work_dir, "frames"), scale=RENDER_SCALE, max_fps=max_fps,
                           progress=lambda i, n: rep("render", 22 + int(28 * i / max(1, n))),
                           backgrounds=backgrounds)
        sheet_dir = os.path.join(work_dir, "wb16")
        os.makedirs(sheet_dir, exist_ok=True)
        jobs = [(p, os.path.join(sheet_dir, f"{i:06d}.png"), content_aspect, OUT_W, OUT_H)
                for i, (t, p) in enumerate(raw)]
        outs = _pmap(_wb16_fit, jobs, RENDER_WORKERS)
        wb_frames = [(raw[i][0], outs[i]) for i in range(len(raw))]
        rep("render", 60)

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
        pat = os.path.join(ss_dir, f"{si}_%05d.png")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", p, "-vf",
                        f"fps=1,scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
                        f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2:color=black", pat], check=False)
        k = 0
        while os.path.exists(os.path.join(ss_dir, f"{si}_{k + 1:05d}.png")):
            ss_frames.append((start + k, os.path.join(ss_dir, f"{si}_{k + 1:05d}.png")))
            k += 1
        if k:
            windows.append((start, start + dur))

    pdf_frames_list, pdf_win = [], None
    if pdf_nav and pdf_paths and not wb.pages:
        rep("render", 74)
        pointer = wb_mod.load_pointer(zf)
        pdf_frames_list, pdf_win = pdf_content_frames(
            pdf_paths, pdf_nav, pointer, os.path.join(work_dir, "sp"), OUT_W, OUT_H)

    def in_share(t):
        return any(a <= t < b for a, b in windows)

    def in_pdf(t):
        return bool(pdf_win) and pdf_win[0] <= t < pdf_win[1]

    frames = ([(t, p) for (t, p) in wb_frames if not in_share(t) and not in_pdf(t)]
              + [(t, p) for (t, p) in pdf_frames_list if not in_share(t)]
              + ss_frames)
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
    cmd += _vcodec_args() + ["-pix_fmt", "yuv420p",
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
    cmd += _vcodec_args() + ["-pix_fmt", "yuv420p",
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

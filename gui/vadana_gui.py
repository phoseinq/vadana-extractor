#!/usr/bin/env python3
"""
Vadana Extractor — desktop GUI (dark).

Paste a recording link, Analyze, then pull the slides PDF, the whiteboard PDF,
the synced video (with a resolution / frame-rate setting), or just the audio
(m4a / mp3). Same things the Telegram bot does, on your desktop.

Run:  python gui/vadana_gui.py   (or double-click vadana-gui.bat)
"""
import os
import sys
import time
import queue
import shutil
import threading
import traceback
import subprocess
import datetime
import tkinter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))   # repo root (for vadana.*)
sys.path.insert(0, _HERE)                    # gui/ (for icons)
import customtkinter as ctk
import icons

from vadana.connect import parse_recording_url, ConnectClient, is_valid_recording
from vadana import whiteboard as wb_mod, audio as audio_mod, video as video_mod
from vadana.slides import download_slides

VERSION = "3.4.9"
OUT_DIR = "out"
LOG_FILE = os.path.join(OUT_DIR, "vadana.log")
MAX_RETRIES = 3
ACCENT, ACCENT_HOVER = "#2dd4bf", "#14b8a6"
CARD, BG, FIELD = "#171a21", "#0f1115", "#0b0d11"
MUTED, TEXT = "#8b93a7", "#d7dce5"
OK_DOT, BAD_DOT = "#34d399", "#f87171"
RES = {"720p": (1280, 720), "1080p": (1920, 1080), "1440p": (2560, 1440), "4K": (3840, 2160)}
STAGE_LABEL = {"audio": "extracting & mixing the lecture audio",
               "render": "rendering the board / slide frames",
               "encode": "encoding the video",
               "done": "finishing up"}

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Vadana Extractor")
        self.geometry("900x860")
        self.minsize(820, 760)
        self.configure(fg_color=BG)

        self._q: queue.Queue = queue.Queue()
        self.client = self.zf = self.rec = None
        self.pdfs = []
        self.busy = False
        self._last_job = None
        self._retries = 0
        self.duration_sec = 0
        self.est_lbl = None

        self._build()
        self.after(80, self._drain)
        self.refresh_prereqs()

    # ── layout ────────────────────────────────────────────────────────────────
    def _build(self):
        pad = {"padx": 22, "pady": (0, 12)}
        DARK = (6, 35, 31, 255)
        self.ic_board = ctk.CTkImage(icons.icon("board", 22), size=(22, 22))
        self.ic_doc = ctk.CTkImage(icons.icon("doc", 22), size=(22, 22))
        self.ic_audio = ctk.CTkImage(icons.icon("audio", 22, icons.ACCENT), size=(22, 22))
        self.ic_folder = ctk.CTkImage(icons.icon("folder", 18), size=(18, 18))
        self.ic_search = ctk.CTkImage(icons.icon("search", 18, DARK), size=(18, 18))
        self.ic_dl = ctk.CTkImage(icons.icon("download", 20, DARK), size=(20, 20))
        self.ic_info = ctk.CTkImage(icons.icon("info", 20), size=(20, 20))
        self.ic_paste = ctk.CTkImage(icons.icon("paste", 18), size=(18, 18))

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=22, pady=(18, 12))
        ctk.CTkButton(head, text="", image=self.ic_info, width=40, height=40, command=self._about,
                      fg_color=CARD, hover_color="#222632", corner_radius=20).pack(side="right", anchor="n")
        ttl = ctk.CTkFrame(head, fg_color="transparent")
        ttl.pack(side="left", anchor="w")
        ctk.CTkLabel(ttl, text="Vadana Extractor", font=ctk.CTkFont(size=26, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(ttl, text="Recover slides · whiteboard · video · audio from a Vadana recording",
                     text_color=MUTED, font=ctk.CTkFont(size=13)).pack(anchor="w")

        # prerequisites strip
        pr = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14)
        pr.pack(fill="x", **pad)
        inner = ctk.CTkFrame(pr, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=10)
        ctk.CTkLabel(inner, text="Prerequisites", text_color=MUTED,
                     font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
        self.dot_ff = self._dot(inner, "ffmpeg")
        self.dot_pk = self._dot(inner, "packages")
        self.fix_btn = ctk.CTkButton(inner, text="Check & install", width=140, height=30,
                                     command=self.fix_prereqs, fg_color=FIELD, hover_color="#222632",
                                     font=ctk.CTkFont(size=12))
        self.fix_btn.pack(side="right")

        # URL row
        url = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14)
        url.pack(fill="x", **pad)
        url.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(url, placeholder_text="Paste the recording URL (with ?session=…)",
                                      height=44, font=ctk.CTkFont(size=13), border_width=0, fg_color=FIELD)
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(14, 8), pady=14)
        self.url_entry.bind("<Return>", lambda e: self.analyze())
        self._enable_paste(self.url_entry)
        ctk.CTkButton(url, text="Paste", image=self.ic_paste, compound="left", width=92, height=44,
                      command=self._paste_url, fg_color=FIELD, hover_color="#222632",
                      font=ctk.CTkFont(size=13)).grid(row=0, column=1, padx=(0, 8), pady=14)
        self.analyze_btn = ctk.CTkButton(url, text="Analyze", image=self.ic_search, compound="left",
                                         width=130, height=44, command=self.analyze,
                                         fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#06231f",
                                         font=ctk.CTkFont(size=14, weight="bold"))
        self.analyze_btn.grid(row=0, column=2, padx=(0, 14), pady=14)

        # contents card
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14)
        card.pack(fill="x", **pad)
        ctk.CTkLabel(card, text="RECORDING CONTENTS", text_color="#5b6478",
                     font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w", padx=18, pady=(12, 0))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(4, 14))
        for i in range(3):
            row.grid_columnconfigure(i, weight=1)
        self.stat_wb = self._stat(row, 0, self.ic_board, "Whiteboard pages")
        self.stat_pdf = self._stat(row, 1, self.ic_doc, "Slides (PDF)")
        self.stat_aud = self._stat(row, 2, self.ic_audio, "Lecture audio")

        # output type
        self.out_type = ctk.CTkSegmentedButton(
            self, values=["Slides PDF", "Whiteboard PDF", "Video", "Audio"],
            command=self._on_type, height=40, font=ctk.CTkFont(size=13),
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER, unselected_color=CARD)
        self.out_type.set("Video")
        self.out_type.pack(fill="x", **pad)

        self.settings = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14, height=70)
        self.settings.pack(fill="x", **pad)
        self.settings.pack_propagate(False)
        self._vid_res = ctk.StringVar(value="1440p")
        self._vid_fps = ctk.StringVar(value="4")
        self._aud_fmt = ctk.StringVar(value="m4a")
        self._build_settings()

        # actions
        act = ctk.CTkFrame(self, fg_color="transparent")
        act.pack(fill="x", padx=22, pady=(2, 10))
        act.grid_columnconfigure(0, weight=1)
        self.extract_btn = ctk.CTkButton(act, text="Extract", image=self.ic_dl, compound="left",
                                         height=48, command=self.extract, state="disabled",
                                         fg_color="#22302e", hover_color=ACCENT_HOVER, text_color="#06231f",
                                         text_color_disabled="#5b6f6a",
                                         font=ctk.CTkFont(size=16, weight="bold"), corner_radius=12)
        self.extract_btn.grid(row=0, column=0, sticky="ew")
        self.retry_btn = ctk.CTkButton(act, text="Retry", width=110, height=48, command=self.retry,
                                       fg_color="#3a2730", hover_color="#5b3a48", text_color="#f9c0cf",
                                       font=ctk.CTkFont(size=14, weight="bold"), corner_radius=12)

        self.bar = ctk.CTkProgressBar(self, height=8, progress_color=ACCENT, fg_color=CARD)
        self.bar.set(0)
        self.bar.pack(fill="x", padx=22, pady=(0, 8))

        # produced files
        self.results = ctk.CTkScrollableFrame(self, fg_color=FIELD, corner_radius=12, height=108,
                                              label_text="  OUTPUT FILES", label_fg_color=CARD,
                                              label_text_color="#5b6478",
                                              label_font=ctk.CTkFont(size=10, weight="bold"))
        self.results.pack(fill="x", padx=22, pady=(0, 8))
        self._results_placeholder()

        self.log = ctk.CTkTextbox(self, fg_color=FIELD, text_color="#9aa4b2", corner_radius=12,
                                  font=ctk.CTkFont(family="Consolas", size=12))
        self.log.pack(fill="both", expand=True, padx=22, pady=(0, 8))
        self.log.configure(state="disabled")

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=22, pady=(0, 14))
        self.out_lbl = ctk.CTkLabel(foot, text=f"Output → {os.path.abspath(OUT_DIR)}",
                                    text_color=MUTED, font=ctk.CTkFont(size=12))
        self.out_lbl.pack(side="left")
        ctk.CTkButton(foot, text="Open output folder", image=self.ic_folder, compound="left",
                      width=185, height=32, command=self._open_out, fg_color=CARD,
                      hover_color="#222632", font=ctk.CTkFont(size=12)).pack(side="right")

    def _dot(self, parent, label):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(side="left", padx=(18, 0))
        d = ctk.CTkLabel(f, text="●", text_color="#4b5563", font=ctk.CTkFont(size=14))
        d.pack(side="left", padx=(0, 5))
        ctk.CTkLabel(f, text=label, text_color=MUTED, font=ctk.CTkFont(size=12)).pack(side="left")
        return d

    def _stat(self, parent, col, image, label):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=0, column=col, sticky="n")
        ctk.CTkLabel(f, text="", image=image).pack(side="left", padx=(0, 10))
        box = ctk.CTkFrame(f, fg_color="transparent")
        box.pack(side="left")
        val = ctk.CTkLabel(box, text="—", text_color=TEXT, font=ctk.CTkFont(size=18, weight="bold"))
        val.pack(anchor="w")
        ctk.CTkLabel(box, text=label, text_color="#6b7280", font=ctk.CTkFont(size=11)).pack(anchor="w")
        return val

    def _build_settings(self):
        for w in self.settings.winfo_children():
            w.destroy()
        t = self.out_type.get()
        self.est_lbl = None
        row = ctk.CTkFrame(self.settings, fg_color="transparent")
        row.pack(expand=True)
        mk = lambda **k: dict(fg_color=FIELD, button_color=ACCENT, button_hover_color=ACCENT_HOVER, **k)
        if t == "Video":
            ctk.CTkLabel(row, text="Quality", text_color=MUTED).grid(row=0, column=0, padx=(0, 8), pady=14)
            ctk.CTkOptionMenu(row, values=list(RES), variable=self._vid_res, width=110,
                              command=self._update_estimate, **mk()).grid(row=0, column=1, padx=(0, 24))
            ctk.CTkLabel(row, text="Frame rate", text_color=MUTED).grid(row=0, column=2, padx=(0, 8))
            ctk.CTkOptionMenu(row, values=["2", "4", "8", "15", "30"], variable=self._vid_fps, width=78,
                              command=self._update_estimate, **mk()).grid(row=0, column=3, padx=(0, 24))
            self.est_lbl = ctk.CTkLabel(row, text="≈ — MB", text_color=ACCENT,
                                        font=ctk.CTkFont(size=15, weight="bold"))
            self.est_lbl.grid(row=0, column=4)
            self._update_estimate()
        elif t == "Audio":
            ctk.CTkLabel(row, text="Format", text_color=MUTED).grid(row=0, column=0, padx=(0, 10), pady=14)
            ctk.CTkSegmentedButton(row, values=["m4a", "mp3"], variable=self._aud_fmt,
                                   selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
                                   unselected_color=FIELD).grid(row=0, column=1)
        else:
            ctk.CTkLabel(row, text="No extra settings for this output.", text_color="#6b7280").pack(pady=20)

    def _on_type(self, _=None):
        self._build_settings()

    def _update_estimate(self, _=None):
        """Rough output-size estimate that reacts to quality + frame rate. Calibrated
        on real builds (1440p@4fps ≈ the audio bitrate + ~1.2 kbps per megapixel per
        fps for the mostly-static board/slides). Just a ballpark — marked with ≈."""
        if self.est_lbl is None:
            return
        if self.duration_sec < 1:
            self.est_lbl.configure(text="≈ — MB")
            return
        w, h = RES[self._vid_res.get()]
        fps = float(self._vid_fps.get())
        kbps = 96 + 1.2 * (w * h / 1_000_000) * fps      # audio + video (static content)
        self.est_lbl.configure(text=f"≈ {kbps * self.duration_sec / 8000:.0f} MB")

    # ── paste / clipboard ─────────────────────────────────────────────────────
    def _enable_paste(self, entry):
        def paste(_=None):
            try:
                txt = self.clipboard_get()
            except Exception:
                return "break"
            try:
                entry.delete("sel.first", "sel.last")   # replace the selection (e.g. after Ctrl+A)
            except Exception:
                pass
            entry.insert("insert", txt)
            return "break"
        menu = tkinter.Menu(self, tearoff=0, bg=CARD, fg=TEXT, activebackground=ACCENT, activeforeground="#06231f")
        menu.add_command(label="Paste", command=paste)
        menu.add_command(label="Copy", command=lambda: entry.event_generate("<<Copy>>"))
        menu.add_command(label="Cut", command=lambda: entry.event_generate("<<Cut>>"))
        menu.add_separator()
        menu.add_command(label="Select all", command=lambda: entry.select_range(0, "end"))
        menu.add_command(label="Clear", command=lambda: entry.delete(0, "end"))
        def on_ctrl(e):
            # match by physical keycode (V=86, A=65 on Windows; 55/38 on X11) so Ctrl+V
            # and Ctrl+A work on any keyboard layout — a Persian layout sends a different keysym
            ks = (getattr(e, "keysym", "") or "").lower()
            if e.keycode in (86, 55) or ks == "v":
                return paste()
            if e.keycode in (65, 38) or ks == "a":
                entry.select_range(0, "end")
                entry.icursor("end")
                return "break"
        entry.bind("<Control-KeyPress>", on_ctrl)
        entry.bind("<Button-2>", paste)
        entry.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

    def _paste_url(self):
        """Layout-independent paste — works no matter the keyboard (Persian etc.)."""
        try:
            txt = self.clipboard_get().strip()
        except Exception:
            txt = ""
        if txt:
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, txt)
            self.url_entry.focus_set()

    # ── worker plumbing ───────────────────────────────────────────────────────
    def _say(self, msg):
        self._q.put(("log", msg))
        try:
            os.makedirs(OUT_DIR, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now():%H:%M:%S}  {msg}\n")
        except Exception:
            pass

    def _prog(self, frac, status=None):
        self._q.put(("prog", (max(0.0, min(1.0, frac)), status)))

    def _drain(self):
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "log":
                    self.log.configure(state="normal")
                    self.log.insert("end", payload + "\n")
                    self.log.see("end")
                    self.log.configure(state="disabled")
                elif kind == "prog":
                    frac, status = payload
                    self.bar.set(frac)
                    if status:
                        self.status_text(status)
                elif kind == "info":
                    wb, pdf, aud = payload
                    self.stat_wb.configure(text=str(wb))
                    self.stat_pdf.configure(text=str(pdf))
                    self.stat_aud.configure(text="yes" if aud else "no")
                    self._update_estimate()
                elif kind == "dots":
                    ff, pk = payload
                    self.dot_ff.configure(text_color=OK_DOT if ff else BAD_DOT)
                    self.dot_pk.configure(text_color=OK_DOT if pk else BAD_DOT)
                elif kind == "results":
                    self._show_results(payload)
                elif kind == "done":
                    failed = payload == "failed"
                    self._set_busy(False)
                    if failed and self._last_job and self._retries < MAX_RETRIES:
                        self.retry_btn.grid(row=0, column=1, padx=(10, 0))
                    else:
                        self.retry_btn.grid_forget()
                        if not failed:
                            self._retries = 0
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def status_text(self, t):
        self.out_lbl.configure(text=t if t.startswith("Output") else f"Output → {os.path.abspath(OUT_DIR)}    ·    {t}")

    def _set_busy(self, busy):
        self.busy = busy
        self.analyze_btn.configure(state="disabled" if busy else "normal")
        self.fix_btn.configure(state="disabled" if busy else "normal")
        ready = not busy and self.zf is not None
        self.extract_btn.configure(state="normal" if ready else "disabled",
                                   fg_color=ACCENT if ready else "#22302e")

    def _run(self, fn, remember=False):
        if self.busy:
            return
        if remember:
            self._last_job = fn
        self._set_busy(True)
        self.retry_btn.grid_forget()
        threading.Thread(target=self._guard(fn), daemon=True).start()

    def _guard(self, fn):
        def inner():
            try:
                fn()
            except Exception as e:
                self._say(f"[!] error: {e}")
                self._say("    " + traceback.format_exc().splitlines()[-1])
                self._q.put(("done", "failed"))
            else:
                self._q.put(("done", None))
        return inner

    # ── prerequisites ─────────────────────────────────────────────────────────
    def _check(self):
        ff = audio_mod.ffmpeg_available()
        try:
            import customtkinter, PIL, fitz, img2pdf, requests  # noqa: F401
            pk = True
        except Exception:
            pk = False
        return ff, pk

    def refresh_prereqs(self):
        ff, pk = self._check()
        self._q.put(("dots", (ff, pk)))
        return ff, pk

    def fix_prereqs(self):
        self._run(self._fix_job)

    def _fix_job(self):
        ff, pk = self._check()
        if pk and ff:
            self._say("[+] all prerequisites are already installed.")
        if not pk:
            self._say("[*] installing Python packages …")
            for req in ("requirements.txt", "requirements-gui.txt"):
                if os.path.exists(req):
                    subprocess.run([sys.executable, "-m", "pip", "install", "-r", req])
        if not ff:
            if os.name == "nt" and shutil.which("winget"):
                self._say("[*] installing ffmpeg via winget … (a window may ask to confirm)")
                subprocess.run(["winget", "install", "-e", "--id", "Gyan.FFmpeg",
                                "--accept-package-agreements", "--accept-source-agreements"])
                self._say("[i] if ffmpeg still shows red, close and reopen this app so PATH refreshes.")
            else:
                self._say("[!] please install ffmpeg (Windows: winget install ffmpeg · macOS: brew install ffmpeg · Linux: apt install ffmpeg).")
        self.refresh_prereqs()

    # ── actions ───────────────────────────────────────────────────────────────
    def analyze(self):
        rec = parse_recording_url(self.url_entry.get().strip())
        if not is_valid_recording(rec):
            self._say("[!] not a valid Adobe Connect / Vadana recording URL.")
            return
        self.rec = rec
        self._last_job = None
        self._retries = 0
        self._run(self._analyze_job)

    def _analyze_job(self):
        self._prog(0.0, "downloading…")
        proxy = os.environ.get("IRAN_PROXY") or None
        self.client = ConnectClient(self.rec.host, self.rec.token, proxy=proxy)
        self._say(f"[*] downloading package {self.rec.rec_id} …")
        self.zf = self.client.open_package(self.rec.rec_id,
                                           lambda g, t: self._prog((g / t * 0.9) if t else 0.3, "downloading…"))
        wb = wb_mod.load_from_package(self.zf)
        work = os.path.join(OUT_DIR, "_work", self.rec.rec_id)
        self.pdfs = download_slides(self.client, self.rec.rec_id, os.path.join(work, "pdfs"),
                                    self.zf, exts={".pdf"}) or []
        segs = audio_mod.main_audio_segments(self.zf)
        has_audio = bool(segs)
        self.duration_sec = video_mod._meta_seconds(self.zf, "mainstream.xml") or 0
        if self.duration_sec < 1 and segs:
            self.duration_sec = audio_mod._xml_total_seconds(self.zf, segs)
        self._q.put(("info", (len(wb.pages), len(self.pdfs), has_audio)))
        self._prog(1.0, "ready")
        self._say(f"[+] whiteboard pages: {len(wb.pages)}   slides: {len(self.pdfs)}   "
                  f"audio: {'yes' if has_audio else 'no'}")

    def extract(self):
        if self.zf is None:
            return
        self._run(self._extract_job, remember=True)

    def retry(self):
        if self._last_job and not self.busy:
            self._retries += 1
            self._say(f"[*] retry {self._retries}/{MAX_RETRIES} …")
            self._run(self._last_job, remember=True)

    def _extract_job(self):
        os.makedirs(OUT_DIR, exist_ok=True)
        work = os.path.join(OUT_DIR, "_work", self.rec.rec_id)
        rid = self.rec.rec_id
        t = self.out_type.get()
        self.bar.set(0)
        produced = []
        if t == "Slides PDF":
            saved = download_slides(self.client, rid, OUT_DIR, self.zf, exts={".pdf"})
            produced = saved or []
            self._say(f"[+] {len(saved)} PDF(s) -> {OUT_DIR}/" if saved else "[!] no shared PDFs.")
        elif t == "Whiteboard PDF":
            out = os.path.join(OUT_DIR, f"{rid}_whiteboard.pdf")
            res = wb_mod.make_pdf(self.zf, out, 2, None, self.pdfs or None)
            if res:
                produced = [out]
            self._say(f"[+] -> {out}" if res else "[!] no whiteboard in this recording.")
        elif t == "Video":
            if not audio_mod.ffmpeg_available():
                self._say("[!] ffmpeg not found — use ‘Check & install’ above."); return
            w, h = RES[self._vid_res.get()]
            out = os.path.join(OUT_DIR, f"{rid}.mp4")
            try:
                enc = video_mod._encoder()
            except Exception:
                enc = "libx264"
            self._say(f"[*] building video  ·  {self._vid_res.get()} ({w}x{h}) @ {self._vid_fps.get()} fps")
            self._say(f"    encoder : {enc}  ({'GPU-accelerated' if enc != 'libx264' else 'CPU (libx264)'})")
            self._say(f"    workers : {video_mod.RENDER_WORKERS} parallel render process(es)")
            t0 = time.time()
            last = [None]

            def vprog(s, p):
                label = STAGE_LABEL.get(s, s)
                if s != last[0]:
                    last[0] = s
                    self._say(f"    ▸ {label} …")
                self._prog(p / 100.0, f"{label}  {p:.0f}%")

            res = video_mod.make_full_video(self.zf, work, out, 2, float(self._vid_fps.get()),
                                            progress=vprog, pdf_paths=self.pdfs or None, out_w=w, out_h=h)
            if res:
                produced = [out]
                mb = os.path.getsize(out) / 1e6
                self._say(f"[+] done in {time.time() - t0:.0f}s  ·  {mb:.1f} MB  ->  {out}")
            else:
                self._say("[!] no whiteboard/screen-share/slides — try Audio for the lecture audio.")
        elif t == "Audio":
            if not audio_mod.ffmpeg_available():
                self._say("[!] ffmpeg not found — use ‘Check & install’ above."); return
            self._prog(0.3, "extracting audio…")
            m4a = os.path.join(OUT_DIR, f"{rid}.m4a")
            if not audio_mod.extract_audio(self.zf, work, m4a):
                self._say("[!] no audio in this recording."); return
            if self._aud_fmt.get() == "mp3":
                mp3 = os.path.join(OUT_DIR, f"{rid}.mp3")
                subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-y", "-loglevel", "error", "-i", m4a,
                                "-c:a", "libmp3lame", "-q:a", "3", mp3], check=True)
                os.remove(m4a)
                produced = [mp3]
                self._say(f"[+] -> {mp3}")
            else:
                produced = [m4a]
                self._say(f"[+] -> {m4a}")
        if produced:
            self._q.put(("results", produced))
        self._prog(1.0, "done")

    def _about(self):
        win = ctk.CTkToplevel(self)
        win.title("About")
        win.geometry("470x470")
        win.configure(fg_color=BG)
        win.resizable(False, False)
        win.after(120, lambda: (win.transient(self), win.lift(), win.grab_set()))
        ctk.CTkLabel(win, text="", image=ctk.CTkImage(icons.icon("info", 40, icons.ACCENT), size=(40, 40))
                     ).pack(pady=(26, 4))
        ctk.CTkLabel(win, text="Vadana Extractor", font=ctk.CTkFont(size=22, weight="bold")).pack()
        ctk.CTkLabel(win, text=f"version {VERSION}", text_color=MUTED, font=ctk.CTkFont(size=12)).pack(pady=(0, 12))
        ctk.CTkLabel(win, text="Recover study material from Adobe Connect (Vadana)\n"
                     "class recordings you're authorised to watch.",
                     text_color=TEXT, justify="center").pack(padx=24)
        body = ("Slides PDF — the original shared PDFs\n"
                "Whiteboard PDF — the professor's board\n"
                "Video — board / slides synced with the audio\n"
                "Audio — the lecture as m4a or mp3\n\n"
                "Needs Python 3.11–3.13 and ffmpeg on PATH.\n"
                "Everything is saved to the out/ folder.")
        box = ctk.CTkFrame(win, fg_color=CARD, corner_radius=12)
        box.pack(fill="x", padx=26, pady=16)
        ctk.CTkLabel(box, text=body, text_color="#9aa4b2", justify="left",
                     font=ctk.CTkFont(size=12)).pack(padx=18, pady=14, anchor="w")
        import webbrowser
        ctk.CTkButton(win, text="GitHub  ·  phoseinq/vadana-extractor", height=34,
                      fg_color=CARD, hover_color="#222632", font=ctk.CTkFont(size=12),
                      command=lambda: webbrowser.open("https://github.com/phoseinq/vadana-extractor")).pack()
        ctk.CTkButton(win, text="Close", width=120, height=34, command=win.destroy,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#06231f").pack(pady=14)

    def _results_placeholder(self):
        for w in self.results.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.results, text="Extracted files will appear here — with a button to reveal them.",
                     text_color="#5b6478", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=8, pady=10)

    def _show_results(self, paths):
        for w in self.results.winfo_children():
            w.destroy()
        paths = [p for p in (paths or []) if p and os.path.exists(p)]
        if not paths:
            self._results_placeholder()
            return
        for p in paths:
            ap = os.path.abspath(p)
            rowf = ctk.CTkFrame(self.results, fg_color=CARD, corner_radius=8)
            rowf.pack(fill="x", padx=4, pady=3)
            ctk.CTkButton(rowf, text="Show in folder", image=self.ic_folder, compound="left",
                          width=140, height=30, command=lambda x=ap: self._reveal(x),
                          fg_color=FIELD, hover_color="#222632",
                          font=ctk.CTkFont(size=11)).pack(side="right", padx=8, pady=8)
            box = ctk.CTkFrame(rowf, fg_color="transparent")
            box.pack(side="left", fill="x", expand=True, padx=12, pady=6)
            size = f"  ·  {os.path.getsize(ap) / 1e6:.1f} MB" if os.path.getsize(ap) > 1e5 else ""
            ctk.CTkLabel(box, text=os.path.basename(ap) + size, text_color=TEXT, anchor="w",
                         font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w")
            ctk.CTkLabel(box, text=ap, text_color="#5b6478", anchor="w",
                         font=ctk.CTkFont(size=10)).pack(anchor="w")

    def _reveal(self, path):
        path = os.path.abspath(path)
        try:
            if os.name == "nt":
                subprocess.run(["explorer", "/select," + path])     # Explorer with the file highlighted
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", path])
            else:
                subprocess.run(["xdg-open", os.path.dirname(path)])
        except Exception:
            self._say(f"[i] file: {path}")

    def _open_out(self):
        os.makedirs(OUT_DIR, exist_ok=True)
        path = os.path.abspath(OUT_DIR)
        try:
            if os.name == "nt":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception:
            self._say(f"[i] output folder: {path}")


if __name__ == "__main__":
    App().mainloop()

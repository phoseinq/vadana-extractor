#!/usr/bin/env python3
"""
Vadana Extractor — desktop GUI (dark).

A small, focused window: paste a recording link, hit Analyze, then pull the
slides PDF, the whiteboard PDF, the synced video (with a quality setting), or
just the audio (m4a / mp3). The same things the Telegram bot does, on your
desktop. Run:  python gui/vadana_gui.py   (or double-click vadana-gui.bat)
"""
import os
import sys
import queue
import threading
import traceback
import subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))   # repo root (for vadana.*)
sys.path.insert(0, _HERE)                    # gui/ (for icons)
import customtkinter as ctk
import icons

from vadana.connect import parse_recording_url, ConnectClient, is_valid_recording
from vadana import whiteboard as wb_mod, audio as audio_mod, video as video_mod
from vadana.slides import download_slides

OUT_DIR = "out"
ACCENT = "#2dd4bf"          # teal
ACCENT_HOVER = "#14b8a6"
RES = {"1080p": (1920, 1080), "1440p": (2560, 1440), "4K": (3840, 2160)}

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Vadana Extractor")
        self.geometry("860x680")
        self.minsize(760, 620)
        self.configure(fg_color="#0f1115")

        self._q: queue.Queue = queue.Queue()
        self.client = None
        self.zf = None
        self.rec = None
        self.pdfs = []
        self.busy = False

        self._build()
        self.after(80, self._drain)

    # ── layout ────────────────────────────────────────────────────────────────
    def _build(self):
        pad = {"padx": 22, "pady": (0, 14)}
        DARK = (6, 35, 31, 255)            # icon colour on the teal buttons
        self.ic_board = ctk.CTkImage(icons.icon("board", 20), size=(20, 20))
        self.ic_doc = ctk.CTkImage(icons.icon("doc", 20), size=(20, 20))
        self.ic_audio = ctk.CTkImage(icons.icon("audio", 20, icons.ACCENT), size=(20, 20))
        self.ic_folder = ctk.CTkImage(icons.icon("folder", 18), size=(18, 18))
        self.ic_search = ctk.CTkImage(icons.icon("search", 18, DARK), size=(18, 18))
        self.ic_dl = ctk.CTkImage(icons.icon("download", 20, DARK), size=(20, 20))

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=22, pady=(20, 14))
        ctk.CTkLabel(head, text="Vadana Extractor", font=ctk.CTkFont(size=26, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(head, text="Recover slides · whiteboard · video · audio from a Vadana recording",
                     text_color="#8b93a7", font=ctk.CTkFont(size=13)).pack(anchor="w")

        # URL row
        url = ctk.CTkFrame(self, fg_color="#171a21", corner_radius=14)
        url.pack(fill="x", **pad)
        url.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(url, placeholder_text="Paste the recording URL (with ?session=…)",
                                      height=44, font=ctk.CTkFont(size=13), border_width=0, fg_color="#0f1115")
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(14, 8), pady=14)
        self.url_entry.bind("<Return>", lambda e: self.analyze())
        self.analyze_btn = ctk.CTkButton(url, text="Analyze", image=self.ic_search, compound="left",
                                         width=120, height=44, command=self.analyze,
                                         fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#06231f",
                                         font=ctk.CTkFont(size=14, weight="bold"))
        self.analyze_btn.grid(row=0, column=1, padx=(0, 14), pady=14)

        # contents card — icon chips
        card = ctk.CTkFrame(self, fg_color="#171a21", corner_radius=14, height=58)
        card.pack(fill="x", **pad)
        card.pack_propagate(False)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(expand=True)
        self.stat_wb = self._chip(inner, self.ic_board, "whiteboard", "—")
        self.stat_pdf = self._chip(inner, self.ic_doc, "slides", "—")
        self.stat_aud = self._chip(inner, self.ic_audio, "audio", "—")

        # output type
        self.out_type = ctk.CTkSegmentedButton(
            self, values=["Slides PDF", "Whiteboard PDF", "Video", "Audio"],
            command=self._on_type, height=40, font=ctk.CTkFont(size=13),
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER, unselected_color="#171a21")
        self.out_type.set("Video")
        self.out_type.pack(fill="x", **pad)

        # settings (swaps with the chosen type)
        self.settings = ctk.CTkFrame(self, fg_color="#171a21", corner_radius=14, height=70)
        self.settings.pack(fill="x", **pad)
        self.settings.pack_propagate(False)
        self._vid_res = ctk.StringVar(value="1440p")
        self._vid_fps = ctk.StringVar(value="4")
        self._aud_fmt = ctk.StringVar(value="m4a")
        self._build_settings()

        # extract
        self.extract_btn = ctk.CTkButton(self, text="Extract", image=self.ic_dl, compound="left",
                                         height=48, command=self.extract,
                                         state="disabled", fg_color="#22302e", hover_color=ACCENT_HOVER,
                                         text_color="#06231f", text_color_disabled="#5b6f6a",
                                         font=ctk.CTkFont(size=16, weight="bold"), corner_radius=12)
        self.extract_btn.pack(fill="x", padx=22, pady=(2, 12))

        self.bar = ctk.CTkProgressBar(self, height=8, progress_color=ACCENT, fg_color="#171a21")
        self.bar.set(0)
        self.bar.pack(fill="x", padx=22, pady=(0, 8))

        self.log = ctk.CTkTextbox(self, fg_color="#0b0d11", text_color="#9aa4b2", corner_radius=12,
                                  font=ctk.CTkFont(family="Consolas", size=12))
        self.log.pack(fill="both", expand=True, padx=22, pady=(0, 8))
        self.log.configure(state="disabled")

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=22, pady=(0, 16))
        self.status = ctk.CTkLabel(foot, text="ready", text_color="#8b93a7", font=ctk.CTkFont(size=12))
        self.status.pack(side="left")
        ctk.CTkButton(foot, text="Open output folder", image=self.ic_folder, compound="left",
                      width=190, height=32, command=self._open_out,
                      fg_color="#171a21", hover_color="#222632", font=ctk.CTkFont(size=12)).pack(side="right")

    def _build_settings(self):
        for w in self.settings.winfo_children():
            w.destroy()
        t = self.out_type.get()
        row = ctk.CTkFrame(self.settings, fg_color="transparent")
        row.pack(expand=True)
        if t == "Video":
            ctk.CTkLabel(row, text="Resolution", text_color="#8b93a7").grid(row=0, column=0, padx=(0, 8), pady=14)
            ctk.CTkOptionMenu(row, values=list(RES), variable=self._vid_res, width=110,
                              fg_color="#0f1115", button_color=ACCENT, button_hover_color=ACCENT_HOVER
                              ).grid(row=0, column=1, padx=(0, 24))
            ctk.CTkLabel(row, text="Frame rate", text_color="#8b93a7").grid(row=0, column=2, padx=(0, 8))
            ctk.CTkOptionMenu(row, values=["2", "4"], variable=self._vid_fps, width=80,
                              fg_color="#0f1115", button_color=ACCENT, button_hover_color=ACCENT_HOVER
                              ).grid(row=0, column=3)
        elif t == "Audio":
            ctk.CTkLabel(row, text="Format", text_color="#8b93a7").grid(row=0, column=0, padx=(0, 10), pady=14)
            ctk.CTkSegmentedButton(row, values=["m4a", "mp3"], variable=self._aud_fmt,
                                   selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
                                   unselected_color="#0f1115").grid(row=0, column=1)
        else:
            ctk.CTkLabel(row, text="No extra settings for this output.", text_color="#6b7280").pack(pady=20)

    def _on_type(self, _=None):
        self._build_settings()

    def _chip(self, parent, image, label_text, value):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(side="left", padx=16)
        ctk.CTkLabel(f, text="", image=image).pack(side="left", padx=(0, 9))
        box = ctk.CTkFrame(f, fg_color="transparent")
        box.pack(side="left")
        val = ctk.CTkLabel(box, text=value, text_color="#d7dce5", font=ctk.CTkFont(size=15, weight="bold"))
        val.pack(anchor="w")
        ctk.CTkLabel(box, text=label_text, text_color="#6b7280", font=ctk.CTkFont(size=10)).pack(anchor="w")
        return val

    # ── worker plumbing ───────────────────────────────────────────────────────
    def _say(self, msg):
        self._q.put(("log", msg))

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
                        self.status.configure(text=status)
                elif kind == "info":
                    wb, pdf, aud = payload
                    self.stat_wb.configure(text=str(wb))
                    self.stat_pdf.configure(text=str(pdf))
                    self.stat_aud.configure(text="yes" if aud else "no")
                elif kind == "done":
                    self._set_busy(False)
                    if payload:
                        self.status.configure(text=payload)
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def _set_busy(self, busy):
        self.busy = busy
        self.analyze_btn.configure(state="disabled" if busy else "normal")
        ready = not busy and self.zf is not None
        self.extract_btn.configure(state="normal" if ready else "disabled",
                                   fg_color=ACCENT if ready else "#22302e")

    def _run(self, fn):
        if self.busy:
            return
        self._set_busy(True)
        threading.Thread(target=self._guard(fn), daemon=True).start()

    def _guard(self, fn):
        def inner():
            try:
                fn()
            except Exception as e:
                self._say(f"[!] error: {e}")
                self._say(traceback.format_exc().splitlines()[-1])
                self._q.put(("done", "failed"))
            else:
                self._q.put(("done", None))
        return inner

    # ── actions ───────────────────────────────────────────────────────────────
    def analyze(self):
        url = self.url_entry.get().strip()
        rec = parse_recording_url(url)
        if not is_valid_recording(rec):
            self._say("[!] not a valid Adobe Connect / Vadana recording URL.")
            return
        self.rec = rec
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
        has_audio = bool(audio_mod.main_audio_segments(self.zf))
        self._q.put(("info", (len(wb.pages), len(self.pdfs), has_audio)))
        self._prog(1.0, "ready")
        self._say(f"[+] whiteboard pages: {len(wb.pages)}   slides: {len(self.pdfs)}   "
                  f"audio: {'yes' if has_audio else 'no'}")

    def extract(self):
        if self.zf is None:
            return
        self._run(self._extract_job)

    def _extract_job(self):
        os.makedirs(OUT_DIR, exist_ok=True)
        work = os.path.join(OUT_DIR, "_work", self.rec.rec_id)
        rid = self.rec.rec_id
        t = self.out_type.get()
        self.bar.set(0)
        if t == "Slides PDF":
            saved = download_slides(self.client, rid, OUT_DIR, self.zf, exts={".pdf"})
            self._say(f"[+] {len(saved)} PDF(s) -> {OUT_DIR}/" if saved else "[!] no shared PDFs.")
        elif t == "Whiteboard PDF":
            out = os.path.join(OUT_DIR, f"{rid}_whiteboard.pdf")
            res = wb_mod.make_pdf(self.zf, out, 2, None, self.pdfs or None)
            self._say(f"[+] -> {out}" if res else "[!] no whiteboard in this recording.")
        elif t == "Video":
            if not audio_mod.ffmpeg_available():
                self._say("[!] ffmpeg not found on PATH."); return
            w, h = RES[self._vid_res.get()]
            out = os.path.join(OUT_DIR, f"{rid}.mp4")
            self._say(f"[*] building {self._vid_res.get()} @ {self._vid_fps.get()}fps … (a few minutes)")
            res = video_mod.make_full_video(
                self.zf, work, out, 2, float(self._vid_fps.get()),
                progress=lambda s, p: self._prog(p / 100.0, f"{s}  {p:.0f}%"),
                pdf_paths=self.pdfs or None, out_w=w, out_h=h)
            self._say(f"[+] -> {out}" if res
                      else "[!] no whiteboard/screen-share/slides — try Audio for the lecture audio.")
        elif t == "Audio":
            if not audio_mod.ffmpeg_available():
                self._say("[!] ffmpeg not found on PATH."); return
            self._prog(0.3, "extracting audio…")
            m4a = os.path.join(OUT_DIR, f"{rid}.m4a")
            if not audio_mod.extract_audio(self.zf, work, m4a):
                self._say("[!] no audio in this recording."); return
            if self._aud_fmt.get() == "mp3":
                mp3 = os.path.join(OUT_DIR, f"{rid}.mp3")
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", m4a,
                                "-c:a", "libmp3lame", "-q:a", "3", mp3], check=True)
                os.remove(m4a)
                self._say(f"[+] -> {mp3}")
            else:
                self._say(f"[+] -> {m4a}")
        self._prog(1.0, "done")

    # ── misc ──────────────────────────────────────────────────────────────────
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

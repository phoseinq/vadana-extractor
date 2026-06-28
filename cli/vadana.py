#!/usr/bin/env python3
"""
Vadana Extractor — interactive CLI (Windows / macOS / Linux).

One command:
    python cli/vadana.py            (or just double-click vadana.bat on Windows)

Paste a recording link, see what it actually contains, then pull what you want:
the shared slides PDF, the whiteboard PDF, the full synced video, or just the
lecture audio (m4a or mp3). It loops, so you can grab several things — or several
recordings — without re-running.
"""
import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vadana.connect import parse_recording_url, ConnectClient, is_valid_recording
from vadana import whiteboard as wb_mod, audio as audio_mod, video as video_mod
from vadana.slides import download_slides

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
if os.name == "nt":
    os.system("")                       # enable ANSI colours in the Windows console

OUT = "out"


def c(s, code):
    return f"\033[{code}m{s}\033[0m"


def ask_url():
    while True:
        url = input(c("\nPaste the recording URL (with ?session=…), blank to quit:\n> ", "96")).strip()
        if not url:
            sys.exit(0)
        rec = parse_recording_url(url)
        if is_valid_recording(rec):
            return rec
        print(c("  ! not a valid Adobe Connect / Vadana recording URL — try again.", "91"))


def run(rec):
    proxy = os.environ.get("IRAN_PROXY") or None
    client = ConnectClient(rec.host, rec.token, proxy=proxy)
    print(c(f"[*] downloading package {rec.rec_id} …", "93"))
    try:
        zf = client.open_package(rec.rec_id)
    except Exception as e:
        print(c(f"[!] could not download: {e}", "91"))
        return

    work = os.path.join(OUT, "_work", rec.rec_id)
    wb = wb_mod.load_from_package(zf)
    pdfs = download_slides(client, rec.rec_id, os.path.join(work, "pdfs"), zf, exts={".pdf"}) or []
    has_audio = bool(audio_mod.main_audio_segments(zf))
    print(c("\nThis recording contains:", "1"))
    print(f"  whiteboard pages : {len(wb.pages)}")
    print(f"  shared PDF slides: {len(pdfs)}")
    print(f"  lecture audio    : {'yes' if has_audio else 'no'}")
    os.makedirs(OUT, exist_ok=True)

    while True:
        print(c("\nWhat do you want?", "1;96"))
        print("  1) Slides PDF      (the original shared PDFs)")
        print("  2) Whiteboard PDF  (the professor's board)")
        print("  3) Synced video    (board/slides + audio)")
        print("  4) Audio only      (m4a or mp3)")
        print("  5) Another recording")
        print("  0) Quit")
        ch = input(c("> ", "96")).strip()
        try:
            if ch == "1":
                saved = download_slides(client, rec.rec_id, OUT, zf, exts={".pdf"})
                print(c(f"[+] {len(saved)} file(s) -> {OUT}/", "92") if saved
                      else c("[!] this recording has no shared PDFs.", "91"))
            elif ch == "2":
                out = os.path.join(OUT, f"{rec.rec_id}_whiteboard.pdf")
                res = wb_mod.make_pdf(zf, out, 2, None, pdfs or None)
                print(c(f"[+] -> {out}", "92") if res else c("[!] no whiteboard in this recording.", "91"))
            elif ch == "3":
                if not audio_mod.ffmpeg_available():
                    print(c("[!] ffmpeg not found on PATH (needed for video).", "91")); continue
                out = os.path.join(OUT, f"{rec.rec_id}.mp4")
                print(c("[*] building the synced video — this takes a few minutes …", "93"))
                res = video_mod.make_full_video(
                    zf, work, out, 2, 4.0,
                    progress=lambda s, p: print(f"\r    {s}  {p:3.0f}%   ", end="", flush=True),
                    pdf_paths=pdfs or None)
                print()
                print(c(f"[+] -> {out}", "92") if res
                      else c("[!] no whiteboard/screen-share/slides — use option 4 for the audio.", "91"))
            elif ch == "4":
                if not audio_mod.ffmpeg_available():
                    print(c("[!] ffmpeg not found on PATH (needed for audio).", "91")); continue
                fmt = input("  format — [1] m4a   [2] mp3 ?  ").strip()
                m4a = os.path.join(OUT, f"{rec.rec_id}.m4a")
                print(c("[*] extracting audio …", "93"))
                if not audio_mod.extract_audio(zf, work, m4a):
                    print(c("[!] no audio in this recording.", "91")); continue
                if fmt == "2":
                    mp3 = os.path.join(OUT, f"{rec.rec_id}.mp3")
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", m4a,
                                    "-c:a", "libmp3lame", "-q:a", "3", mp3], check=True)
                    os.remove(m4a)
                    print(c(f"[+] -> {mp3}", "92"))
                else:
                    print(c(f"[+] -> {m4a}", "92"))
            elif ch == "5":
                return run(ask_url())
            elif ch == "0":
                return
            else:
                print(c("  ? pick a number from 0 to 5.", "91"))
        except Exception as e:
            print(c(f"[!] error: {e}", "91"))


def main():
    print(c("\n=== Vadana Extractor ===", "1;96"))
    print("Recover slides / whiteboard / video / audio from an Adobe Connect (Vadana) recording.")
    run(ask_url())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()

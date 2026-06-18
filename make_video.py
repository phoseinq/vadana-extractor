#!/usr/bin/env python3
import argparse
import os
import sys
import zipfile

from vadana.connect import parse_recording_url, ConnectClient
from vadana import whiteboard as wb_mod
from vadana import audio as audio_mod
from vadana import video as video_mod

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

def load_package(args):
    if args.package:
        rec_id = os.path.splitext(os.path.basename(args.package))[0]
        return zipfile.ZipFile(args.package), rec_id
    rec = parse_recording_url(args.url)
    if not rec.token:
        sys.exit("[!] link has no ?session= — paste the live recording URL.")
    print(f"[*] downloading package {rec.rec_id} ...")
    proxy = os.environ.get("IRAN_PROXY") or None
    return ConnectClient(rec.host, rec.token, proxy=proxy).open_package(rec.rec_id), rec.rec_id

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", help="recording URL with ?session=")
    ap.add_argument("--package", help="use a local <id>.zip package instead")
    ap.add_argument("--out")
    ap.add_argument("--pages-only", action="store_true")
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--fps", type=float, default=4.0)
    ap.add_argument("--audio-offset", type=int, default=0)
    args = ap.parse_args()
    if not args.url and not args.package:
        ap.error("give a recording URL or --package <file.zip>")

    zf, rec_id = load_package(args)
    out_dir = "out"
    work = os.path.join(out_dir, "_work", rec_id)
    os.makedirs(work, exist_ok=True)

    print("[*] parsing whiteboard ...")
    wb = wb_mod.load_from_package(zf)
    print(f"[*] {len(wb.pages)} page(s), {len(wb.events)} events, "
          f"~{wb.duration_ms/60000:.1f} min")

    if args.pages_only:
        if not wb.pages:
            print("[!] no whiteboard content (maybe shared documents — use download_slides.py).")
            return
        out = args.out or os.path.join(out_dir, f"{rec_id}_whiteboard.pdf")
        os.makedirs(out_dir, exist_ok=True)
        imgs = wb_mod.render_final_pages(wb, args.scale)
        wb_mod.save_pdf(imgs, out)
        print(f"[+] {len(imgs)} pages -> {out}")
        return

    if not audio_mod.ffmpeg_available():
        sys.exit("[!] ffmpeg not found on PATH (needed for video).")

    out = args.out or os.path.join(out_dir, f"{rec_id}.mp4")
    os.makedirs(out_dir, exist_ok=True)
    print("[*] building synced video (whiteboard + screen-share + audio) ...")
    res = video_mod.make_full_video(zf, work, out, args.scale, args.fps,
                                    progress=lambda s, p: print(f"\r    {s}  {p:3.0f}%   ", end="", flush=True))
    print()
    if not res:
        print("[!] nothing to build (no whiteboard and no screen-share).")
        return
    print(f"[+] DONE -> {out}")

if __name__ == "__main__":
    main()

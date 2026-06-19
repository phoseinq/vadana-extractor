#!/usr/bin/env python3
import os
import sys

from vadana.connect import parse_recording_url, ConnectClient
from vadana.slides import download_slides

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

def collect_links() -> list[str]:
    args = [a for a in sys.argv[1:] if a.strip()]
    if args:
        return args
    if os.path.exists("links.txt"):
        with open("links.txt", encoding="utf-8") as f:
            links = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        if links:
            print(f"[*] {len(links)} link(s) from links.txt")
            return links
    print("Paste recording links (one per line). Empty line = start:\n")
    links = []
    while True:
        try:
            line = input().strip()
        except EOFError:
            break
        if not line:
            break
        links.append(line)
    return links

def main():
    links = collect_links()
    if not links:
        print("No links given.")
        return
    total_ok = total = 0
    for i, link in enumerate(links, 1):
        rec = parse_recording_url(link)
        print(f"\n========== [{i}/{len(links)}] {rec.rec_id} ==========")
        client = ConnectClient(rec.host, rec.token, proxy=os.environ.get("IRAN_PROXY") or None)
        try:
            saved = download_slides(client, rec.rec_id, os.path.join("slides", rec.rec_id))
        except Exception as e:
            print(f"[!] {e}")
            continue
        if not saved:
            print("[!] no shared PDFs (whiteboard/screen-only session).")
        for p in saved:
            print(f"  saved {os.path.basename(p)}")
        total_ok += len(saved)
        total += len(saved)
    print(f"\n[*] done: {total_ok} file(s) -> ./slides/")

if __name__ == "__main__":
    main()

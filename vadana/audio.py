from __future__ import annotations

import os
import re
import subprocess
import zipfile

def ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False

def _seg_key(name: str):
    nums = re.findall(r"\d+", name)
    return [int(n) for n in nums]

def main_audio_segments(zf: zipfile.ZipFile, min_bytes: int = 100_000) -> list[str]:
    """cameraVoip FLVs big enough to be the lecturer's stream, in playback order."""
    segs = [i.filename for i in zf.infolist()
            if i.filename.lower().startswith("cameravoip") and i.filename.lower().endswith(".flv")
            and i.file_size >= min_bytes]
    return sorted(segs, key=_seg_key)

def _xml_total_seconds(zf, flv_names) -> float:
    """Total audio duration from the cameraVoip XML metadata (FLV ffprobe says N/A)."""
    total = 0.0
    for n in flv_names:
        try:
            d = zf.read(n.rsplit(".", 1)[0] + ".xml").decode("utf-8", "replace")
        except KeyError:
            continue
        m = re.search(r"onMetaData.*?<Number><!\[CDATA\[([\d.]+)\]\]>", d, re.S)
        if m:
            total += float(m.group(1))
    return total

def extract_audio(zf: zipfile.ZipFile, workdir: str, out_path: str, progress=None) -> str | None:
    """Concatenate the main cameraVoip audio into out_path. progress(frac) 0..1."""
    segs = main_audio_segments(zf)
    if not segs:
        return None
    os.makedirs(workdir, exist_ok=True)
    local = []
    for s in segs:
        p = os.path.join(workdir, os.path.basename(s))
        with open(p, "wb") as f:
            f.write(zf.read(s))
        local.append(p)
    total = _xml_total_seconds(zf, segs)

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if progress and total > 0:
        cmd += ["-progress", "pipe:1", "-nostats"]
    for p in local:
        cmd += ["-i", p]
    if len(local) == 1:
        cmd += ["-vn", "-c:a", "aac", "-b:a", "96k", out_path]
    else:
        streams = "".join(f"[{i}:a]" for i in range(len(local)))
        cmd += ["-filter_complex", f"{streams}concat=n={len(local)}:v=0:a=1[a]",
                "-map", "[a]", "-c:a", "aac", "-b:a", "96k", out_path]

    if progress and total > 0:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        for line in proc.stdout:
            if line.startswith(("out_time_us=", "out_time_ms=")):
                try:
                    v = int(line.strip().split("=", 1)[1])
                    secs = v / (1e6 if "us=" in line else 1e3)
                    progress(max(0.0, min(1.0, secs / total)))
                except Exception:
                    pass
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError("ffmpeg audio failed")
    else:
        subprocess.run(cmd, check=True)
    return out_path

def duration_seconds(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0

from __future__ import annotations

import os
import re
import subprocess

_STREAM_RE = re.compile(
    r"<startTime><!\[CDATA\[(\d+)\]\]></startTime>\s*"
    r"<streamId><!\[CDATA\[[^\]]*\]\]></streamId>\s*"
    r"<streamName><!\[CDATA\[/([^\]]+)\]\]></streamName>\s*"
    r"<streamPublisherID><!\[CDATA\[([^\]]*)\]\]></streamPublisherID>\s*"
    r"<streamType><!\[CDATA\[([^\]]+)\]\]></streamType>",
    re.S,
)

def parse_streams(indexstream_xml: str) -> list[dict]:
    """Unique stream segments with their master start time (ms), name and type."""
    seen, out = set(), []
    for m in _STREAM_RE.finditer(indexstream_xml):
        name = m.group(2)
        if name in seen:
            continue
        seen.add(name)
        out.append({"start_ms": int(m.group(1)), "name": name,
                    "pub": m.group(3), "type": m.group(4)})
    return out

def build_master_audio(zf, streams, workdir, out_path, min_bytes=50_000) -> str | None:
    """Mix every cameraVoip segment onto one full-length track at its real offset."""
    os.makedirs(workdir, exist_ok=True)
    auds = []
    for s in streams:
        if s["type"] != "cameraVoip":
            continue
        flv = s["name"] + ".flv"
        try:
            data = zf.read(flv)
        except KeyError:
            continue
        if len(data) < min_bytes:
            continue
        p = os.path.join(workdir, os.path.basename(flv))
        with open(p, "wb") as f:
            f.write(data)
        auds.append((p, s["start_ms"]))
    if not auds:
        return None

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for p, _ in auds:
        cmd += ["-i", p]
    parts, labels = [], []
    for i, (_, delay) in enumerate(auds):
        parts.append(f"[{i}:a]aresample=44100,adelay={delay}|{delay}[a{i}]")
        labels.append(f"[a{i}]")
    parts.append(f"{''.join(labels)}amix=inputs={len(auds)}:dropout_transition=0:normalize=0[a]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[a]", "-c:a", "aac", "-b:a", "96k", out_path]
    subprocess.run(cmd, check=True)
    return out_path

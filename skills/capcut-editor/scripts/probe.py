#!/usr/bin/env python3
"""Inspect source media so edit decisions rest on what is actually in the files.

  probe.py a.mp4 b.mov song.mp3                # duration, size, fps, audio for each file
  probe.py a.mp4 --sheet out_dir [--frames 12] # contact sheet JPG to LOOK at the footage
  probe.py a.mp4 --sheet out_dir --from 10 --to 20   # zoom the sheet into a time window
  probe.py a.mp4 --scenes                      # shot-change timestamps
  probe.py talk.mp4 --silence                  # silent gaps + speech segments (for jump cuts)
  probe.py song.mp3 --beats                    # tempo and beat timestamps (for cutting on the beat)
  probe.py talk.mp4 song.mp3 --loudness        # LUFS and true peak, to level speech and music

Output is JSON on stdout. Needs ffmpeg/ffprobe on PATH (--beats also needs numpy).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".tif", ".tiff"}


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def info(path: Path) -> dict:
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    if r.returncode != 0:
        return {"file": str(path), "error": r.stderr.strip()[:300]}
    data = json.loads(r.stdout)
    out = {"file": str(path)}
    v = next((s for s in data["streams"] if s["codec_type"] == "video"
              and s.get("disposition", {}).get("attached_pic", 0) == 0), None)
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    duration = float(data.get("format", {}).get("duration") or 0)
    if v:
        w, h = int(v["width"]), int(v["height"])
        rot = 0
        for sd in v.get("side_data_list", []):
            if "rotation" in sd:
                rot = int(sd["rotation"])
        rot = int(v.get("tags", {}).get("rotate", rot))
        if abs(rot) % 180 == 90:
            w, h = h, w
        num, _, den = (v.get("avg_frame_rate") or "0/1").partition("/")
        fps = float(num) / float(den or 1) if float(den or 1) else 0
        is_image = path.suffix.lower() in IMAGE_EXT or (duration == 0 and int(v.get("nb_frames", 1) or 1) <= 1)
        g = math.gcd(w, h) or 1
        out.update({"kind": "image" if is_image else "video", "width": w, "height": h,
                    "aspect": f"{w // g}:{h // g}",
                    "orientation": "vertical" if h > w else "horizontal" if w > h else "square"})
        if not is_image:
            out.update({"duration": round(duration, 3), "fps": round(fps, 3), "has_audio": a is not None})
    elif a:
        out.update({"kind": "audio", "duration": round(duration, 3)})
    else:
        out["error"] = "no audio or video stream"
    return out


def sheet(path: Path, meta: dict, out_dir: Path, frames: int, t0, t1) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    start = max(0.0, t0 or 0.0)
    end = min(meta["duration"], t1) if t1 else meta["duration"]
    span = max(0.1, end - start)
    cols = 4 if frames > 6 else 3
    rows = math.ceil(frames / cols)
    width = 270 if meta["height"] > meta["width"] else 400
    target = out_dir / f"{path.stem}_sheet_{int(start)}-{int(math.ceil(end))}.jpg"
    r = run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{span:.3f}", "-i", str(path),
             "-vf", f"fps={frames}/{span:.4f},scale={width}:-2,tile={cols}x{rows}:padding=4:margin=4",
             "-frames:v", "1", "-q:v", "4", str(target)])
    if r.returncode != 0 or not target.exists():
        return {"error": r.stderr.strip()[:300]}
    step = span / frames
    return {"image": str(target), "grid": f"{cols} columns x {rows} rows, read left-to-right then down",
            "approx_times": [round(start + step * (i + 0.5), 2) for i in range(frames)]}


def scenes(path: Path, threshold: float) -> list:
    r = run(["ffmpeg", "-v", "info", "-i", str(path), "-an", "-vf",
             f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"])
    return [round(float(m), 3) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr)]


def silence(path: Path, meta: dict, noise_db: float, min_len: float) -> dict:
    r = run(["ffmpeg", "-v", "info", "-i", str(path), "-vn", "-af",
             f"silencedetect=noise={noise_db}dB:d={min_len}", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: (-?[0-9.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", r.stderr)]
    total = meta.get("duration", 0)
    gaps = [[round(max(0, s), 3), round(ends[i] if i < len(ends) else total, 3)] for i, s in enumerate(starts)]
    speech, cursor = [], 0.0
    for s, e in gaps:
        if s - cursor > 0.15:
            speech.append([round(cursor, 3), round(s, 3)])
        cursor = e
    if total - cursor > 0.15:
        speech.append([round(cursor, 3), round(total, 3)])
    return {"silences": gaps, "sound_segments": speech,
            "hint": "use sound_segments as in/out pairs (pad ~0.1s) to cut dead air"}


def loudness(path: Path) -> dict | None:
    """Integrated loudness (LUFS, EBU R128: silence is gated out) and true peak (dBTP) of a file's
    sound, or None when it has none."""
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
             "loudnorm=print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr)
    if not m:
        return None
    data = json.loads(m.group(0))
    try:
        lufs, peak = float(data["input_i"]), float(data["input_tp"])
    except (KeyError, ValueError):
        return None
    if not math.isfinite(lufs) or lufs < -70:  # silent
        return None
    return {"lufs": round(lufs, 1), "peak_db": round(peak, 1)}


def beats(path: Path) -> dict:
    try:
        import numpy as np
    except ImportError:
        return {"error": "numpy is required for --beats (pip install numpy)"}
    sr, hop, win = 22050, 512, 1024
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
                        "-f", "f32le", "-"], capture_output=True)
    y = np.frombuffer(p.stdout, dtype=np.float32)
    if y.size < sr:
        return {"error": "could not decode at least one second of audio"}
    n = 1 + (y.size - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    mag = np.abs(np.fft.rfft(y[idx] * np.hanning(win), axis=1))
    flux = np.maximum(0, np.diff(np.log1p(100 * mag), axis=0)).sum(axis=1)
    flux = flux - np.convolve(flux, np.ones(43) / 43, mode="same")  # remove slow trend (~1s)
    flux = np.maximum(0, flux)
    if flux.max() <= 0:
        return {"error": "no rhythmic energy detected"}
    flux /= flux.max()
    fps = sr / hop
    ac = np.correlate(flux, flux, mode="full")[flux.size - 1:]
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 70)
    lags = np.arange(lo, hi)
    # prefer tempi near 120 BPM when candidates tie (common octave ambiguity)
    weight = np.exp(-0.5 * (np.log2((60 * fps / lags) / 120) / 0.9) ** 2)
    period = int(lags[np.argmax(ac[lo:hi] * weight)])
    bpm = 60 * fps / period
    # dynamic programming beat tracker (Ellis 2007): follow strong onsets ~one period apart
    score, back = flux.copy(), np.full(flux.size, -1)
    prev = np.arange(-2 * period, -period // 2)
    penalty = -100 * (np.log(-prev / period)) ** 2
    for i in range(flux.size):
        cand = i + prev
        ok = cand >= 0
        if ok.any():
            vals = score[cand[ok]] + penalty[ok]
            j = int(np.argmax(vals))
            score[i] = flux[i] + vals[j]
            back[i] = cand[ok][j]
    i = int(np.argmax(score[-2 * period:]) + flux.size - 2 * period) if flux.size > 2 * period else int(np.argmax(score))
    track = []
    while i >= 0:
        track.append(i)
        i = int(back[i])
    times = [round(((b + 1) * hop + win / 2) / sr, 3) for b in reversed(track)]  # flux[b] is the rise into frame b+1
    strength = [float(flux[b]) for b in reversed(track)]
    # the strongest of the 4 phase offsets is the most likely downbeat position
    phase = int(np.argmax([np.mean(strength[k::4]) for k in range(4)])) if len(times) >= 8 else 0
    # loudness curve, to locate the drop / high-energy sections
    block = sr
    rms = [float(np.sqrt(np.mean(y[k:k + block] ** 2))) for k in range(0, y.size - block + 1, block)]
    peak = max(rms) or 1.0
    return {"bpm": round(bpm, 1), "beat_interval": round(60 / bpm, 3), "beats": times,
            "likely_downbeats": times[phase::4],
            "energy_per_second": [round(v / peak, 2) for v in rms],
            "hint": "cut on beats; put big moments on downbeats; energy jumps mark drops/chorus"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--sheet", metavar="DIR", help="write a contact-sheet JPG per video into DIR")
    ap.add_argument("--frames", type=int, default=12)
    ap.add_argument("--from", dest="t0", type=float)
    ap.add_argument("--to", dest="t1", type=float)
    ap.add_argument("--scenes", action="store_true")
    ap.add_argument("--scene-threshold", type=float, default=0.3)
    ap.add_argument("--silence", action="store_true")
    ap.add_argument("--noise-db", type=float, default=-35.0)
    ap.add_argument("--min-silence", type=float, default=0.4)
    ap.add_argument("--beats", action="store_true")
    ap.add_argument("--loudness", action="store_true")
    args = ap.parse_args()

    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        print("ERROR: ffmpeg and ffprobe must be installed and on PATH", file=sys.stderr)
        return 2

    results = []
    for f in args.files:
        path = Path(f)
        if not path.is_file():
            results.append({"file": f, "error": "file not found"})
            continue
        meta = info(path)
        if "error" not in meta:
            if args.sheet and meta["kind"] == "video":
                meta["sheet"] = sheet(path, meta, Path(args.sheet), max(1, min(args.frames, 30)), args.t0, args.t1)
            if args.scenes and meta["kind"] == "video":
                meta["scene_changes"] = scenes(path, args.scene_threshold)
            if args.silence and (meta["kind"] == "audio" or meta.get("has_audio")):
                meta["silence"] = silence(path, meta, args.noise_db, args.min_silence)
            if args.beats and (meta["kind"] == "audio" or meta.get("has_audio")):
                meta["beats"] = beats(path)
            if args.loudness and (meta["kind"] == "audio" or meta.get("has_audio")):
                meta["loudness"] = loudness(path)
        results.append(meta)
    text = json.dumps(results, ensure_ascii=False, indent=1)
    for _ in range(2):  # keep number lists on one line
        text = re.sub(r"\[\s+([^\[\]{}]*?)\s+\]", lambda m: "[" + " ".join(m.group(1).split()) + "]", text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

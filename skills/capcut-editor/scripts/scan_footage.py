#!/usr/bin/env python3
"""Sort a pile of footage the way an editor would before cutting: find the shots, score them, drop the
duplicates, find the best few seconds of each, and say how to make them look like one video.

  scan_footage.py <folder or files...> --out <dir> [--window 3] [--canvas 1080x1920]

Writes <dir>/footage.json and <dir>/best.jpg (the top shots, numbered by rank, to Read). For each
shot: file, in/out, score 0-100 with the reasons, sharpness, exposure, saturation, shake, motion,
the best window (in/out) and its peak moment, where text reads best ("text_y": 0.5 top, 0 middle,
-0.5 bottom), duplicates and similar shots, the look of the light (day,
golden, night, ...), a color correction toward the rest of the library ("adjust", for the spec),
and for a vertical canvas the horizontal crop offset that keeps the action in frame ("reframe_x").

Needs ffmpeg and numpy. Times are seconds in the source file.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".3gp"}
SAMPLE_FPS = 4
W, H = 320, 180  # analysis size (16:9); other shapes are padded by ffmpeg


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,avg_frame_rate:stream_tags=rotate:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True)
    d = json.loads(r.stdout or "{}")
    st = (d.get("streams") or [{}])[0]
    num, _, den = (st.get("avg_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0
    w, h = int(st.get("width", 0)), int(st.get("height", 0))
    if abs(int((st.get("tags") or {}).get("rotate", 0) or 0)) % 180 == 90:
        w, h = h, w
    return {"duration": float((d.get("format") or {}).get("duration") or 0), "fps": round(fps, 3), "width": w, "height": h}


def frames(path, width, height):
    """RGB frames at SAMPLE_FPS, fitted into width x height (aspect kept, padded black)."""
    vf = (f"fps={SAMPLE_FPS},scale={width}:{height}:force_original_aspect_ratio=decrease,"
          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True)
    raw = np.frombuffer(r.stdout, np.uint8)
    n = raw.size // (width * height * 3)
    return raw[: n * width * height * 3].reshape(n, height, width, 3).astype(np.float32) / 255


def gray(f):
    return f[..., 0] * 0.299 + f[..., 1] * 0.587 + f[..., 2] * 0.114


def sharpness(g):
    """Variance of the Laplacian: high for crisp detail, low for blur."""
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var() * 1000)


def saturation(f):
    hi, lo = f.max(axis=-1), f.min(axis=-1)
    return float(np.mean(np.where(hi > 0, (hi - lo) / np.maximum(hi, 1e-6), 0)))


def shift(a, b):
    """Global translation from frame a to b (pixels), by phase correlation."""
    fa, fb = np.fft.fft2(a - a.mean()), np.fft.fft2(b - b.mean())
    r = fa * np.conj(fb)
    r /= np.abs(r) + 1e-9
    c = np.abs(np.fft.ifft2(r))
    y, x = np.unravel_index(np.argmax(c), c.shape)
    if y > a.shape[0] // 2:
        y -= a.shape[0]
    if x > a.shape[1] // 2:
        x -= a.shape[1]
    return float(x), float(y)


def smooth(x, k=5):
    """Moving average with the ends held (no dip toward zero at the edges)."""
    k = min(k, len(x)) | 1
    if k < 3:
        return x
    xp = np.pad(x, (k // 2, k // 2), mode="edge")
    return np.convolve(xp, np.ones(k) / k, "valid")


def dhash(g):
    """144-bit difference hash (9 x 16 gradient signs) of a gray frame, for duplicate shots."""
    h, w = g.shape
    small = np.array([[g[y * h // 9:(y + 1) * h // 9, x * w // 17:(x + 1) * w // 17].mean() for x in range(17)]
                      for y in range(9)])
    return (small[:, 1:] > small[:, :-1]).ravel()


def light(mean, sat, warmth):
    if mean < 0.18:
        return "night"
    if warmth > 0.08 and sat > 0.3:
        return "golden"
    if mean > 0.62:
        return "bright"
    return "day"


def analyse(path):
    info = probe(path)
    vertical = info["height"] > info["width"]
    aw, ah = (H, W) if vertical else (W, H)  # analyse in the source's own orientation
    fr = frames(path, aw, ah)
    if len(fr) < 2:
        return info, []
    g = np.stack([gray(f) for f in fr])
    t = np.arange(len(fr)) / SAMPLE_FPS
    diff = np.abs(np.diff(g, axis=0)).mean(axis=(1, 2))                       # motion / activity
    hist = np.stack([np.histogram(x, bins=32, range=(0, 1))[0] / x.size for x in g])
    cut = np.abs(np.diff(hist, axis=0)).sum(axis=1)                          # histogram change
    bounds = [0] + [i + 1 for i, c in enumerate(cut) if c > 0.55 and diff[i] > 0.06] + [len(fr)]
    shots = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a < 3:  # under 0.75 s: a flash or a cut-in-cut, not a usable shot
            continue
        seg = slice(a, b)
        sharp = np.array([sharpness(x) for x in g[seg]])
        mean = g[seg].mean(axis=(1, 2))
        sat = np.array([saturation(f) for f in fr[seg]])
        moves = [shift(g[i], g[i + 1]) for i in range(a, b - 1)]
        dx = np.array([m[0] for m in moves]) if moves else np.zeros(1)
        dy = np.array([m[1] for m in moves]) if moves else np.zeros(1)
        # shake = jitter around the smooth camera path (a pan is smooth, a shaky hand is not)
        jitter = np.hypot(dx - smooth(dx), dy - smooth(dy))
        act = diff[a:b - 1] if b - 1 > a else np.zeros(1)
        # where the action is, left to right (for reframing a horizontal shot to vertical)
        energy = np.abs(np.diff(g[seg], axis=0)).mean(axis=(0, 1)) if b - a > 1 else np.ones(aw)
        cx = float((energy * np.arange(aw)).sum() / max(energy.sum(), 1e-9) / aw)
        rgb = fr[seg].mean(axis=(0, 1, 2))
        # where text reads best: the band (top / middle / bottom) with the least light and detail
        mid = g[(a + b) // 2]
        bands = []
        for name, (lo, hi), y in (("top", (0.15, 0.4), 0.5), ("middle", (0.4, 0.6), 0.0), ("bottom", (0.6, 0.85), -0.5)):
            band = mid[int(lo * ah):int(hi * ah)]
            busy = float(np.abs(np.diff(band, axis=1)).mean()) * 10
            bands.append((float(band.mean()) + busy, y))
        text_y = min(bands)[1]
        shots.append({
            "t0": round(float(t[a]), 2), "t1": round(min(float(t[b - 1]) + 1 / SAMPLE_FPS, info["duration"]), 2),
            "sharp": sharp, "mean": mean, "sat": sat, "jitter": jitter, "act": act,
            "center_x": cx, "warmth": float(rgb[0] - rgb[2]), "hash": dhash(g[(a + b) // 2]), "rgb": rgb,
            "text_y": text_y,
            "thumb": fr[(a + b) // 2],
        })
    return info, shots


def best_window(shot, length):
    """The `length`-second stretch with the best mix of sharp, steady and lively frames."""
    n = len(shot["sharp"])
    win = max(1, min(n, int(round(length * SAMPLE_FPS))))
    sharp = shot["sharp"] / (shot["sharp"].max() + 1e-9)
    jit = np.concatenate([shot["jitter"], shot["jitter"][-1:]])[:n]
    act = np.concatenate([shot["act"], shot["act"][-1:]])[:n]
    act = act / (act.max() + 1e-9)
    quality = sharp - 0.4 * np.clip(jit / 3, 0, 1) + 0.3 * act
    scores = np.convolve(quality, np.ones(win) / win, "valid")
    i = int(np.argmax(scores))
    peak = i + int(np.argmax(act[i:i + win]))
    t0 = shot["t0"] + i / SAMPLE_FPS
    return round(t0, 2), round(min(t0 + win / SAMPLE_FPS, shot["t1"]), 2), round(shot["t0"] + peak / SAMPLE_FPS, 2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--window", type=float, default=3.0, help="length of the best window per shot, seconds")
    ap.add_argument("--canvas", default="1080x1920", help="target canvas, for reframe_x")
    ap.add_argument("--top", type=int, default=24, help="shots on the contact sheet")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    files = []
    for inp in args.inputs:
        p = Path(inp)
        files += sorted(f for f in p.iterdir() if f.suffix.lower() in VIDEO_EXT) if p.is_dir() else [p]
    if not files:
        print("no video files found", file=sys.stderr)
        return 2
    cw, ch = (int(v) for v in args.canvas.lower().split("x"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for f in files:
        info, shots = analyse(f)
        for k, s in enumerate(shots):
            rows.append({"file": str(f.resolve()), "name": f.name, "shot": k, "info": info, **s})
        print(f"{f.name}: {len(shots)} shot(s)", file=sys.stderr)
    if not rows:
        print("no usable shots", file=sys.stderr)
        return 1

    # library-relative scores: footage from one phone or one shoot shares a scale
    sharp_ref = float(np.median([np.median(r["sharp"]) for r in rows])) or 1.0
    for r in rows:
        sh = float(np.median(r["sharp"]))
        mean, sat = float(np.median(r["mean"])), float(np.median(r["sat"]))
        jit = float(np.median(r["jitter"])) if len(r["jitter"]) else 0.0
        act = float(np.median(r["act"])) if len(r["act"]) else 0.0
        reasons, score = [], 100.0
        rel = sh / sharp_ref
        if rel < 0.2:
            score -= 45
            reasons.append("blurry or very soft (little detail)")
        elif rel < 0.35:
            score -= 30
            reasons.append("blurry or out of focus")
        elif rel < 0.6:
            score -= 20
            reasons.append("soft")
        if mean < 0.14:
            score -= 30
            reasons.append("very dark")
        elif mean < 0.22 and light(mean, sat, r["warmth"]) != "night":
            score -= 15
            reasons.append("underexposed")
        if mean > 0.8:
            score -= 20
            reasons.append("overexposed")
        if jit > 2.5:
            score -= 35
            reasons.append("shaky")
        elif jit > 1.2:
            score -= 12
            reasons.append("a little shaky")
        if act < 0.004:
            score -= 8
            reasons.append("almost no movement (fine for a hold or a title)")
        dur = r["t1"] - r["t0"]
        if dur < 1.5:
            score -= 15
            reasons.append("very short")
        w_in, w_out, peak = best_window(r, args.window)
        # appeal separates clean shots: crisp detail, color, and something happening
        appeal = (0.4 * min(rel / 2, 1) + 0.3 * min(sat / 0.5, 1) + 0.3 * min(act / 0.04, 1))
        score = max(0.0, score) * 0.8 + appeal * 20
        r.update({"score": int(max(0, min(100, round(score)))), "reasons": reasons or ["clean"],
                  "stats": {"sharpness": round(rel, 2), "exposure": round(mean, 3), "saturation": round(sat, 3),
                            "shake": round(jit, 2), "motion": round(act, 4)},
                  "best": {"in": w_in, "out": w_out, "peak": peak},
                  "light": light(mean, sat, r["warmth"])})

    # duplicates: the same footage twice (a copy, a re-export, an edited version); keep the best one.
    # similar: the same scene shot twice; both are usable, but not next to each other.
    rows.sort(key=lambda r: -r["score"])
    def same(a, b):
        bits = int((a["hash"] != b["hash"]).sum())
        color = float(np.abs(a["rgb"] - b["rgb"]).sum())
        length = abs((a["t1"] - a["t0"]) - (b["t1"] - b["t0"]))
        same_cut = length < 0.3 and abs(a["t0"] - b["t0"]) < 0.3  # the same stretch of the same length
        # an edited copy (graded, darkened, blurred) moves exactly like the original, frame by frame;
        # two takes of the same scene do not
        n = min(len(a["act"]), len(b["act"]))
        moves_alike = (n >= 4 and float(np.std(a["act"][:n])) > 0 and float(np.std(b["act"][:n])) > 0
                       and float(np.corrcoef(a["act"][:n], b["act"][:n])[0, 1]) > 0.9)
        if bits <= 12 or (same_cut and (color < 0.06 or moves_alike)):
            return "duplicate"
        if bits <= 26 and color < 0.3:
            return "similar"
        return None
    keepers = []
    for r in rows:
        r["duplicate_of"], r["similar_to"] = None, []
        for k in keepers:
            rel = same(k, r)
            if rel == "duplicate":
                r["duplicate_of"] = f"{k['name']}#{k['shot']}"
                break
            if rel == "similar":
                r["similar_to"].append(f"{k['name']}#{k['shot']}")
        if r["duplicate_of"] is None:
            keepers.append(r)

    # color: pull every keeper toward the library's typical exposure and saturation
    keep = [r for r in rows if r["duplicate_of"] is None and r["score"] >= 50] or rows
    t_mean = float(np.median([r["stats"]["exposure"] for r in keep]))
    t_sat = float(np.median([r["stats"]["saturation"] for r in keep]))
    # Only daylight shots are matched: night, fireworks and golden-hour light are the mood, not a fault.
    # Saturation is only raised (dull phone footage), never taken out of a vivid shot.
    day = [r for r in keep if r["light"] in ("day", "bright")] or keep
    t_mean = float(np.median([r["stats"]["exposure"] for r in day]))
    t_sat = float(np.median([r["stats"]["saturation"] for r in day]))
    for r in rows:
        r["adjust"] = {}
        if r["light"] not in ("day", "bright"):
            continue
        b = float(np.clip((t_mean - r["stats"]["exposure"]) * 1.2, -0.2, 0.25))
        sat = float(np.clip((t_sat - r["stats"]["saturation"]) * 1.2, 0, 0.25))
        r["adjust"] = {k: round(v, 2) for k, v in (("brightness", b), ("saturation", sat)) if abs(v) >= 0.06}

    # reframe: a horizontal source on a vertical canvas with "fit": "cover"
    for r in rows:
        iw, ih = r["info"]["width"] or W, r["info"]["height"] or H
        shown_w = ch * iw / ih  # canvas px when the height fills the canvas
        if shown_w <= cw * 1.05:
            r["reframe_x"] = 0.0
            continue
        limit = (shown_w - cw) / 2 / (cw / 2)
        x = -(r["center_x"] - 0.5) * shown_w / (cw / 2)
        r["reframe_x"] = round(float(np.clip(x, -limit, limit)), 3)

    ranked = [r for r in rows if r["duplicate_of"] is None]

    # the footage's own accent color: the most common vivid hue across the keepers, made bright enough
    # to read as text (a sunset gives orange, a reef teal, a party magenta)
    px = np.concatenate([r["thumb"].reshape(-1, 3) for r in ranked if r["score"] >= 50] or [ranked[0]["thumb"].reshape(-1, 3)])
    hi, lo = px.max(axis=1), px.min(axis=1)
    vivid = px[((hi - lo) / np.maximum(hi, 1e-6) > 0.45) & (hi > 0.35)]
    accent = None
    if len(vivid) > 200:
        r_, g_, b_ = vivid[:, 0], vivid[:, 1], vivid[:, 2]
        mx = vivid.max(axis=1)
        mn = vivid.min(axis=1)
        d = np.maximum(mx - mn, 1e-6)
        hue = np.where(mx == r_, ((g_ - b_) / d) % 6, np.where(mx == g_, (b_ - r_) / d + 2, (r_ - g_) / d + 4)) / 6
        bins = np.floor(hue * 12).astype(int) % 12
        top = np.bincount(bins, minlength=12).argmax()
        c = vivid[bins == top].mean(axis=0)
        c = c / max(c.max(), 1e-6)  # full brightness keeps the hue and reads on footage
        accent = "#" + "".join(f"{int(round(v * 255)):02X}" for v in c)
    energy = float(np.median([r["stats"]["motion"] for r in ranked])) if ranked else 0.0
    lights = {}
    for r in ranked:
        lights[r["light"]] = lights.get(r["light"], 0) + 1
    dupes = [r for r in rows if r["duplicate_of"] is not None]
    clean = lambda r: {"rank": None, "file": r["file"], "name": r["name"], "shot": r["shot"],
                       "in": r["t0"], "out": r["t1"], "score": r["score"], "reasons": r["reasons"],
                       "best": r["best"], "light": r["light"], "stats": r["stats"], "adjust": r["adjust"],
                       "reframe_x": r["reframe_x"], "fps": r["info"]["fps"], "duplicate_of": r["duplicate_of"],
                       "similar_to": r["similar_to"], "text_y": r["text_y"],
                       "orientation": "vertical" if r["info"]["height"] > r["info"]["width"] else "horizontal"}
    shots = [clean(r) for r in ranked]
    for i, s in enumerate(shots, 1):
        s["rank"] = i
    report = {"files": len(files), "shots": len(rows), "keepers": sum(1 for s in shots if s["score"] >= 50),
              "duplicates": [clean(r) for r in dupes], "target": {"exposure": round(t_mean, 3), "saturation": round(t_sat, 3)},
              "palette": {"accent": accent, "energy": round(energy, 4),
                          "pace": "high" if energy > 0.03 else "low", "light": lights},
              "ranked": shots,
              "note": "Use shots with score >= 50, best window first. 'adjust' goes into the clip's \"adjust\"; "
                      "'reframe_x' into transform.x with \"fit\": \"cover\" on a vertical canvas. Slow motion only "
                      "on fps >= 50."}
    (out / "footage.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    # contact sheet of the top shots, labelled by rank
    from PIL import Image, ImageDraw
    top = ranked[: args.top]
    cols = 4
    tw, th = 320, 180
    sheet = Image.new("RGB", (cols * (tw + 10) + 10, ((len(top) + cols - 1) // cols) * (th + 44) + 10), (40, 40, 40))
    draw = ImageDraw.Draw(sheet)
    for i, r in enumerate(top):
        x0, y0 = 10 + (i % cols) * (tw + 10), 10 + (i // cols) * (th + 44)
        thumb = Image.fromarray((r["thumb"] * 255).astype(np.uint8))
        thumb.thumbnail((tw, th))  # a vertical shot is fitted into the cell, not pasted over the labels
        sheet.paste(thumb, (x0 + (tw - thumb.width) // 2, y0 + (th - thumb.height) // 2))
        draw.text((x0, y0 + th + 3), f"#{i + 1} {r['score']}  {r['name'][:30]}", fill=(255, 220, 0))
        draw.text((x0, y0 + th + 19), f"{r['best']['in']}-{r['best']['out']}s  {r['light']}  {', '.join(r['reasons'])[:34]}",
                  fill=(210, 210, 210))
    sheet.save(out / "best.jpg", quality=88)
    print(json.dumps({"files": len(files), "shots": len(rows), "keepers": report["keepers"],
                      "duplicates": len(dupes), "report": str(out / "footage.json"), "sheet": str(out / "best.jpg"),
                      "top": [f"#{s['rank']} {s['score']} {s['name']} {s['best']['in']}-{s['best']['out']}s"
                              for s in shots[:10]],
                      "bottom": [f"{s['score']} {s['name']}: {', '.join(s['reasons'])}" for s in shots[-5:]]},
                     indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

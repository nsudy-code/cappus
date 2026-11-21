#!/usr/bin/env python3
"""Find the speaker's face in a video, so crops, punch-ins and text can be placed around it.

  faces.py talk.mp4                        # where the face is, and how to frame it on 1080x1920
  faces.py talk.mp4 --from 10 --to 25      # only part of the file
  faces.py talk.mp4 --canvas 1080x1080     # another canvas

Prints JSON: how often a face was found, the face box (fractions of the frame: cx, cy from the
left/top, w, h), a track over time, and for the canvas with "fit": "cover":
  - "reframe_x" (transform.x that centres the face when a wide shot is cropped to vertical),
    or "reframe_path" ([source_seconds, x] for transform.x_path) when the speaker moves across,
  - "punch": the transform for a punch-in that keeps the face where it was,
  - "caption_y" / "title_y": text positions (spec y units) that stay off the face.

cut_talk.py uses this by itself. Needs ffmpeg, numpy and OpenCV, an optional dependency:
  python -m pip install -r requirements-faces.txt     (opencv-python-headless<5, ~40 MB)
Without it, it exits with code 3 and says so.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SAMPLE_FPS = 2.0
WIDTH = 480          # analysis width; a face filling 6% of the height is ~20 px tall at 9:16
CAPTION_Y = -0.6     # the builder's caption position, and where cut_talk puts captions
TITLE_Y = 0.5


INSTALL = 'python -m pip install "opencv-python-headless<5"'


def available() -> bool:
    """OpenCV with its bundled face cascades (OpenCV 5 moved them out of the main package)."""
    try:
        import cv2
    except ImportError:
        return False
    return hasattr(cv2, "CascadeClassifier") and hasattr(cv2, "data")


def _frames(path, iw, ih, fps, start, length):
    import numpy as np
    w = WIDTH if iw >= ih else int(round(WIDTH * iw / ih / 2)) * 2
    h = int(round(w * ih / iw / 2)) * 2
    span = ["-ss", f"{start:.3f}"] if start else []
    span += ["-t", f"{length:.3f}"] if length else []
    r = subprocess.run(["ffmpeg", "-v", "error", *span, "-i", str(path), "-vf", f"fps={fps},scale={w}:{h}",
                        "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
    raw = np.frombuffer(r.stdout, np.uint8)
    n = raw.size // (w * h)
    return raw[: n * w * h].reshape(n, h, w), w, h


def track(path, iw, ih, start=0.0, end=None, fps=SAMPLE_FPS):
    """[(source_seconds, cx, cy, w, h)] of the largest face per sampled frame, as fractions of the
    frame, with one-off detections far from their neighbours removed."""
    import cv2
    import numpy as np
    frames, w, h = _frames(path, iw, ih, fps, start, (end - start) if end else None)
    front = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    side = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")
    small = int(0.06 * min(w, h * 9 / 16 if w < h else h))
    out = []
    for i, g in enumerate(frames):
        g = cv2.equalizeHist(g)
        found = front.detectMultiScale(g, scaleFactor=1.1, minNeighbors=6, minSize=(small, small))
        if len(found) == 0:
            found = side.detectMultiScale(g, scaleFactor=1.1, minNeighbors=6, minSize=(small, small))
        if len(found) == 0:
            continue
        x, y, fw, fh = max(found, key=lambda b: b[2] * b[3])
        out.append((round(start + i / fps, 2), (x + fw / 2) / w, (y + fh / 2) / h, fw / w, fh / h))
    if len(out) >= 3:  # drop a detection that jumps away from both neighbours (a poster, a pattern)
        cx = np.array([p[1] for p in out])
        keep = [0 < i < len(out) - 1 and abs(cx[i] - cx[i - 1]) > 0.15 and abs(cx[i] - cx[i + 1]) > 0.15
                for i in range(len(out))]
        out = [p for p, bad in zip(out, keep) if not bad]
    return out


def geometry(iw, ih, cw, ch):
    """Canvas size of the source under "fit": "cover", in canvas px."""
    k = max(cw / iw, ch / ih)
    return iw * k, ih * k


def framing(face, iw, ih, cw, ch, punch=1.18):
    """Wide and punched transforms for a face box (cx, cy, w, h) under cover.

    Wide: centred on the face sideways when the source is wider than the canvas (a crop), never moved
    up or down. Punched: scaled `punch`, moved so the face stays where it was in the wide framing,
    and never so far that the picture's edge shows."""
    cx, cy = face[0], face[1]
    sw, sh = geometry(iw, ih, cw, ch)
    fx = (cx - 0.5) * sw / (cw / 2)       # face position in spec x units at scale 1, centred
    fy = (0.5 - cy) * sh / (ch / 2)
    lim = lambda shown, c, s: max(0.0, (s * shown - c) / c)
    clamp = lambda v, m: max(-m, min(m, v))
    xw = clamp(-fx, lim(sw, cw, 1.0))
    wide = {"x": round(xw, 3)} if abs(xw) > 0.005 else {}
    xp = clamp(xw + fx * (1 - punch), lim(sw, cw, punch))
    yp = clamp(fy * (1 - punch), lim(sh, ch, punch))
    punched = {"scale": round(punch, 3), "y": round(yp, 3)}
    if abs(xp) > 0.005:
        punched["x"] = round(xp, 3)
    return wide, punched


def text_spots(face, iw, ih, cw, ch, punch=1.18):
    """caption_y and title_y (spec y units) clear of the face in both framings, or None for no room."""
    _, sh = geometry(iw, ih, cw, ch)
    cy, fh = face[1], face[3]
    # face top/bottom on the canvas in spec y (1 = top), the punched framing makes it bigger
    half = fh * sh / ch * punch
    centre = (0.5 - cy) * sh / (ch / 2)
    top, bottom = centre + half + 0.04, centre - half - 0.04
    caption = CAPTION_Y if CAPTION_Y + 0.08 < bottom else None
    if caption is None and bottom > -0.62:  # face low but some room under it
        caption = round(max(-0.62, bottom - 0.08), 3) if bottom - 0.08 > -0.62 else None
    if caption is None:
        caption = round(min(0.7, top + 0.08), 3) if top + 0.08 < 0.7 else None
    title = TITLE_Y if TITLE_Y - 0.1 > top else (round(top + 0.1, 3) if top + 0.1 < 0.72 else None)
    if title is None:  # the head is at the top of the frame: the title goes on the chest, under the chin
        below = round(min(bottom - 0.12, 0.3), 3)
        title = below if caption is None or below - (caption or 0) > 0.3 else None
    return caption, title


def summarize(points, iw, ih, cw, ch, punch=1.18, total=None):
    import numpy as np
    if not points:
        return {"found": 0.0, "face": None}
    arr = np.array([p[1:] for p in points])
    face = [round(float(v), 3) for v in np.median(arr, axis=0)]
    wide, punched = framing(face, iw, ih, cw, ch, punch)
    caption_y, title_y = text_spots(face, iw, ih, cw, ch, punch)
    out = {"face": dict(zip(("cx", "cy", "w", "h"), face)), "wide": wide, "punch": punched,
           "caption_y": caption_y, "title_y": title_y}
    if total:
        out["found"] = round(min(1.0, len(points) / max(1, total)), 2)
    sw, _ = geometry(iw, ih, cw, ch)
    if sw > cw * 1.05:  # a crop: follow the face if it moves further than a fixed crop allows
        xs = [framing((p[1], p[2]), iw, ih, cw, ch, punch)[0].get("x", 0.0) for p in points]
        out["reframe_x"] = wide.get("x", 0.0)
        if max(xs) - min(xs) > 0.35:
            out["reframe_path"] = path_of(points, xs)
    return out


def path_of(points, xs):
    """A few [t, x] keyframes along the face: a moving median, kept where it bends."""
    import numpy as np
    sm = [float(np.median(xs[max(0, i - 2):i + 3])) for i in range(len(xs))]
    pts = [[points[i][0], sm[i]] for i in range(len(sm))]

    def rdp(p, tol):
        if len(p) <= 2:
            return p
        (t0, x0), (t1, x1) = p[0], p[-1]
        d = [abs(x - (x0 + (x1 - x0) * (t - t0) / ((t1 - t0) or 1))) for t, x in p[1:-1]]
        i = int(np.argmax(d)) + 1
        return [p[0], p[-1]] if d[i - 1] <= tol else rdp(p[:i + 1], tol)[:-1] + rdp(p[i:], tol)
    return [[round(t, 2), round(x, 3)] for t, x in rdp(pts, 0.06)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--from", dest="t0", type=float, default=0.0)
    ap.add_argument("--to", dest="t1", type=float)
    ap.add_argument("--canvas", default="1080x1920")
    ap.add_argument("--punch", type=float, default=1.18)
    ap.add_argument("--fps", type=float, default=SAMPLE_FPS)
    args = ap.parse_args()
    if not available():
        print(f"OpenCV with face cascades is not installed: {INSTALL}", file=sys.stderr)
        return 3
    import probe
    path = Path(args.video)
    meta = probe.info(path)
    if meta.get("kind") != "video":
        raise SystemExit(f"{path.name} is not a video: {meta.get('error', meta.get('kind'))}")
    cw, ch = (int(v) for v in args.canvas.lower().split("x"))
    end = args.t1 or meta["duration"]
    pts = track(path, meta["width"], meta["height"], args.t0, end, args.fps)
    total = int((end - args.t0) * args.fps)
    out = {"file": str(path), "width": meta["width"], "height": meta["height"], "canvas": f"{cw}x{ch}",
           **summarize(pts, meta["width"], meta["height"], cw, ch, args.punch, total),
           "track": [list(p[:3]) for p in pts]}
    if not pts:
        out["note"] = "no face found: frame by eye (probe.py --sheet) and pass --face-y to cut_talk.py"
    text = json.dumps(out, ensure_ascii=False, indent=1)
    print(text.replace("\n   ", " ").replace("\n  ]", "]"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""How well a text color reads against the footage behind it.

The builder knows which main-track clip plays under a text and where the text sits, so it grabs that
frame (ffmpeg, small, cached), measures the area behind the text, and compares it with the text
color as a WCAG contrast ratio. 4.5:1 reads easily; under 3:1 text washes into the picture.
"""
from __future__ import annotations

import subprocess

import numpy as np

READABLE = 3.0
WHITE, DARK = "#FFFFFF", "#111111"
_frames: dict = {}


def luminance(rgb):
    """Relative luminance (WCAG) of sRGB values in 0..1 (array or tuple)."""
    c = np.asarray(rgb, dtype=float)
    lin = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return lin[..., 0] * 0.2126 + lin[..., 1] * 0.7152 + lin[..., 2] * 0.0722


def ratio(l1, l2):
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def hex_rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def frame(path, t, width=480):
    """RGB frame of a video (or the image) at t seconds, width px wide, 0..1, or None."""
    key = (path, round(t, 1))
    if key not in _frames:
        try:
            probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                    "stream=width,height", "-of", "csv=p=0", path], capture_output=True, text=True,
                                   timeout=20)
            w, h = (int(v) for v in probe.stdout.strip().split(",")[:2])
            height = max(2, int(round(width * h / w / 2)) * 2)
            out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", path, "-frames:v", "1",
                                  "-vf", f"scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                 capture_output=True, timeout=30)
            img = np.frombuffer(out.stdout, np.uint8)
            _frames[key] = img[: width * height * 3].reshape(height, width, 3) / 255 if img.size >= width * height * 3 else None
        except (OSError, ValueError, subprocess.SubprocessError):
            _frames[key] = None
    return _frames[key]


def behind(clip, t, canvas, x, y, box_w, box_h):
    """Mean color of the area of the clip's frame under a text box on the canvas.

    clip: {"src", "in", "start", "speed", "photo", "fit", "tx", "w", "h"} (times in seconds);
    x, y: the text centre in half-canvas units; box_w, box_h: its size in canvas pixels."""
    img = frame(clip["src"], 0 if clip["photo"] else clip["in"] + (t - clip["start"]) * clip["speed"])
    if img is None:
        return None
    cw, ch = canvas
    ih, iw = img.shape[:2]
    src_aspect, canvas_aspect = clip["w"] / clip["h"], cw / ch
    # how the clip sits on the canvas: shown size in canvas px, then the canvas box in source fractions
    if (clip["fit"] == "cover") == (src_aspect > canvas_aspect):
        shown_h, shown_w = ch, ch * src_aspect          # height fills
    else:
        shown_w, shown_h = cw, cw / src_aspect          # width fills
    left = cw / 2 - shown_w / 2 + clip["tx"] * cw / 2
    top = ch / 2 - shown_h / 2
    cx, cy = cw / 2 + x * cw / 2, ch / 2 - y * ch / 2
    fx0, fx1 = (cx - box_w / 2 - left) / shown_w, (cx + box_w / 2 - left) / shown_w
    fy0, fy1 = (cy - box_h / 2 - top) / shown_h, (cy + box_h / 2 - top) / shown_h
    fx0, fx1, fy0, fy1 = (min(1, max(0, v)) for v in (fx0, fx1, fy0, fy1))
    if fx1 - fx0 < 0.01 or fy1 - fy0 < 0.01:
        return None  # the text sits over the blank (or blurred) part of the canvas
    region = img[int(fy0 * ih):max(int(fy0 * ih) + 1, int(fy1 * ih)), int(fx0 * iw):max(int(fx0 * iw) + 1, int(fx1 * iw))]
    return region.reshape(-1, 3)


def judge(pixels, color):
    """(contrast ratio of color over the area, the natural choice of white or dark there).

    The ratio is taken against a bright spot (70th percentile) for light text and a dark spot (30th)
    for dark text: text has to read over most of what it covers, not just on average. White or dark
    follows the area's overall brightness, so night and sunset shots get white text and only a truly
    bright background (sand, snow, sky, a white wall) gets dark text."""
    lum = luminance(pixels)
    text = float(luminance(hex_rgb(color)))
    bg = float(np.percentile(lum, 70 if text > 0.4 else 30))
    natural = DARK if float(np.median(lum)) > 0.45 else WHITE
    return ratio(text, bg), natural

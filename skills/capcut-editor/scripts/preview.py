#!/usr/bin/env python3
"""Render a rough, low-res preview of an edit spec with ffmpeg, without CapCut.

  preview.py spec.json --out DIR             # DIR/preview.mp4 and DIR/sheet.jpg
  preview.py spec.json --out DIR --size 640  # longer side in pixels (default 960)
  preview.py spec.json --out DIR --fps 10 --every 0.5

The spec is resolved by the same code as build_draft.py (styles, looks, @references, captions,
motion presets), so times and positions match the draft. What the preview draws:

  - main-track clips and overlays: in/out, speed, fit cover/contain, blur or color background,
    transform (x, y, scale, rotation, opacity, flip) and keyframes, so push_in/pan and other motion
  - texts and captions at their times, positions and sizes, in a stand-in font, with stroke and box
  - audio: clip sound and audio items with volume, fades and ducking

What it does not draw: CapCut effects, filters, transitions (cuts are hard), intro/outro/loop
animations, masks, blend modes, chroma key, Remove BG, stickers and the real fonts. Every frame is
stamped "PREVIEW - approximate", and the report lists what was left out. Use it to check the cut,
timing, framing and where text sits; judge the look in CapCut.

Needs ffmpeg on PATH, Pillow and numpy.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from _common import SpecError, font_width
import easing
from build_draft import Builder

LABEL = "PREVIEW - approximate"
NOT_DRAWN = ("effects, filters, transitions, intro/outro/loop animations, masks, blend modes, chroma key, "
             "Remove BG, stickers and the real fonts are not drawn")
FONT_FILES = ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf",
              "C:/Windows/Fonts/arialbd.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/Library/Fonts/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
EM_PER_SIZE = 4.7  # CapCut font size 1 is about 4.7 px of em on a 1080 px wide canvas


# ---------- small helpers ----------
def _font(px: int):
    px = max(6, int(round(px)))
    for name in FONT_FILES:
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    try:
        return ImageFont.load_default(px)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _rgb(c, alpha=1.0) -> tuple:
    """(r, g, b) floats 0-1, or '#RRGGBB[AA]', -> RGBA ints."""
    if isinstance(c, str):
        h = c.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        a = int(h[6:8], 16) / 255 if len(h) >= 8 else 1.0
        return r, g, b, int(round(255 * a * alpha))
    return tuple(int(round(255 * float(v))) for v in c[:3]) + (int(round(255 * alpha)),)


def _curve(a, b):
    """The cubic-bezier (x1, y1, x2, y2) that easing.apply wrote on the segment a -> b, or None."""
    right, left = getattr(a, "_right", None), getattr(b, "_left", None)
    d, dv = b.time_offset - a.time_offset, float(b.values[0]) - float(a.values[0])
    if not (right and left) or d <= 0:
        return None
    if dv == 0:
        return (right[0] / d, 0.0, 1 + left[0] / d, 1.0)
    return (right[0] / d, right[1] / dv, 1 + left[0] / d, 1 + left[1] / dv)


def _kf(seg) -> dict:
    """Keyframes by property name: [(seconds from segment start, value, curve into it), ...]."""
    out = {}
    for kl in getattr(seg, "common_keyframes", []) or []:
        kfs = sorted(kl.keyframes, key=lambda k: k.time_offset)
        pts = [(k.time_offset / 1e6, float(k.values[0]), _curve(kfs[i - 1], k) if i else None)
               for i, k in enumerate(kfs)]
        if pts:
            out[kl.keyframe_property.name] = pts
    return out


def _at(pts, t, default):
    if not pts:
        return default
    if t <= pts[0][0]:
        return pts[0][1]
    for (t0, v0, _), (t1, v1, curve) in zip(pts, pts[1:]):
        if t <= t1:
            if t1 <= t0:
                return v0
            u = (t - t0) / (t1 - t0)
            return v0 + (v1 - v0) * (easing.bezier_at(curve, u) if curve else u)
    return pts[-1][1]


def _transform(seg, t) -> dict:
    """Clip settings at t seconds into the segment, keyframes applied."""
    cs, kf = seg.clip_settings, seg._kf
    sx = sy = None
    if "uniform_scale" in kf:
        sx = sy = _at(kf["uniform_scale"], t, cs.scale_x)
    sx = _at(kf.get("scale_x"), t, cs.scale_x if sx is None else sx)
    sy = _at(kf.get("scale_y"), t, cs.scale_y if sy is None else sy)
    return {"sx": sx, "sy": sy, "x": _at(kf.get("position_x"), t, cs.transform_x),
            "y": _at(kf.get("position_y"), t, cs.transform_y), "rot": _at(kf.get("rotation"), t, cs.rotation),
            "alpha": _at(kf.get("alpha"), t, cs.alpha), "fh": cs.flip_horizontal, "fv": cs.flip_vertical}


def _max_scale(seg) -> tuple:
    cs, kf = seg.clip_settings, seg._kf
    xs = [cs.scale_x] + [p[1] for k in ("uniform_scale", "scale_x") for p in kf.get(k, [])]
    ys = [cs.scale_y] + [p[1] for k in ("uniform_scale", "scale_y") for p in kf.get(k, [])]
    return max(xs), max(ys)


def _place(canvas: Image.Image, img: Image.Image, tr: dict, scale_xy=None):
    """Paste img (already at scale_xy, default its own size) centred where the transform says."""
    W, H = canvas.size
    if scale_xy is not None and (abs(img.width - scale_xy[0]) > 1 or abs(img.height - scale_xy[1]) > 1):
        img = img.resize((max(1, int(round(scale_xy[0]))), max(1, int(round(scale_xy[1])))), Image.BILINEAR)
    if tr["fh"]:
        img = ImageOps.mirror(img)
    if tr["fv"]:
        img = ImageOps.flip(img)
    if abs(tr["rot"]) > 0.05:
        img = img.rotate(-tr["rot"], resample=Image.BILINEAR, expand=True)
    if tr["alpha"] < 0.999:
        a = img.getchannel("A").point(lambda v: int(v * max(0.0, tr["alpha"])))
        img.putalpha(a)
    cx = W / 2 + tr["x"] * W / 2
    cy = H / 2 - tr["y"] * H / 2
    _paste_clipped(canvas, img, int(round(cx - img.width / 2)), int(round(cy - img.height / 2)))


def _paste_clipped(canvas, img, x, y):
    """alpha_composite that allows the image to hang over the canvas edges (cover, zoom, pan)."""
    W, H = canvas.size
    l, t = max(0, -x), max(0, -y)
    r, b = min(img.width, W - x), min(img.height, H - y)
    if r <= l or b <= t:
        return
    canvas.alpha_composite(img.crop((l, t, r, b)), (x + l, y + t))


def _has_audio(path: str, cache={}) -> bool:
    if path not in cache:
        try:
            out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                                  "-of", "csv=p=0", path], capture_output=True, text=True, timeout=60)
            cache[path] = bool(out.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            cache[path] = False
    return cache[path]


def _atempo(speed: float) -> list:
    out = []
    while speed > 100:
        out.append("atempo=100")
        speed /= 100
    while speed < 0.5:
        out.append("atempo=0.5")
        speed /= 0.5
    if abs(speed - 1) > 1e-6:
        out.append(f"atempo={speed:.6f}")
    return out


def _vol_expr(pts, base) -> str:
    """Piecewise-linear volume keyframes as an ffmpeg expression in t."""
    if not pts:
        return f"{base:.4f}"
    expr = f"{pts[-1][1]:.4f}"
    for (t0, v0, *_), (t1, v1, *_) in reversed(list(zip(pts, pts[1:]))):
        seg = f"{v0:.4f}" if t1 <= t0 else f"({v0:.4f}+({v1 - v0:.4f})*(t-{t0:.4f})/{t1 - t0:.4f})"
        expr = f"if(lt(t,{t1:.4f}),{seg},{expr})"
    return f"if(lt(t,{pts[0][0]:.4f}),{pts[0][1]:.4f},{expr})"


# ---------- layers ----------
class VideoLayer:
    """One video/photo segment, decoded at preview size by ffmpeg and streamed frame by frame."""

    def __init__(self, seg, track, canvas, fps, main):
        self.seg, self.track, self.main = seg, track, main
        self.start = seg.target_timerange.start / 1e6
        self.end = self.start + seg.target_timerange.duration / 1e6
        self.W, self.H = canvas
        mat = seg.material_instance
        self.path = mat.path
        self.photo = mat.material_type == "photo"
        mw, mh = seg.material_size
        self.fit = min(self.W / mw, self.H / mh)  # CapCut scale 1.0 = contained in the canvas
        self.base = (mw * self.fit, mh * self.fit)
        msx, msy = _max_scale(seg)
        cap = 3 * max(self.W, self.H)
        self.dec = (max(2, min(cap, int(round(self.base[0] * msx / 2)) * 2)),
                    max(2, min(cap, int(round(self.base[1] * msy / 2)) * 2)))
        self.fps = fps
        self.proc = None
        self.img = None
        self.index = -1
        self.bg = seg.background_filling

    def frame(self, t) -> Image.Image:
        if self.photo:
            if self.img is None:
                im = ImageOps.exif_transpose(Image.open(self.path)).convert("RGBA")
                self.img = im.resize(self.dec, Image.BILINEAR)
            return self.img
        want = int(round((t - self.start) * self.fps))
        if self.proc is None:
            src = self.seg.source_timerange
            speed = self.seg.speed.speed
            vf = (f"setpts=(PTS-STARTPTS)/{speed:.6f},fps={self.fps},"
                  f"scale={self.dec[0]}:{self.dec[1]}:flags=bilinear,format=rgba")
            self.proc = subprocess.Popen(
                ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{src.start / 1e6:.4f}", "-t",
                 f"{src.duration / 1e6:.4f}", "-i", self.path, "-vf", vf, "-an", "-f", "rawvideo", "-"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        size = self.dec[0] * self.dec[1] * 4
        while self.index < want:
            buf = self.proc.stdout.read(size)
            if len(buf) < size:  # the source ran out: hold the last frame
                break
            self.img = Image.frombuffer("RGBA", self.dec, buf, "raw", "RGBA", 0, 1)
            self.index += 1
        if self.img is None:
            self.img = Image.new("RGBA", self.dec, (0, 0, 0, 255))
        return self.img

    def draw(self, canvas, t):
        img = self.frame(t)
        tr = _transform(self.seg, t - self.start)
        if self.main and self.bg is not None:
            if self.bg.fill_type == "canvas_color":
                canvas.alpha_composite(Image.new("RGBA", canvas.size, _rgb(self.bg.color)))
            else:
                k = max(self.W / img.width, self.H / img.height)
                small = img.resize((max(1, int(img.width * k / 4)), max(1, int(img.height * k / 4))), Image.BILINEAR)
                small = small.filter(ImageFilter.GaussianBlur(2 + 10 * float(self.bg.blur)))
                big = small.resize((int(small.width * 4), int(small.height * 4)), Image.BILINEAR)
                _paste_clipped(canvas, big, (self.W - big.width) // 2, (self.H - big.height) // 2)
        _place(canvas, img, tr, (self.base[0] * tr["sx"], self.base[1] * tr["sy"]))

    def close(self):
        if self.proc is not None:
            self.proc.stdout.close()
            self.proc.kill()
            self.proc.wait()
            self.proc = None


class TextLayer:
    """A text segment drawn once with Pillow in a stand-in bold font, then placed per frame."""

    def __init__(self, seg, canvas, k):
        self.seg = seg
        self.start = seg.target_timerange.start / 1e6
        self.end = self.start + seg.target_timerange.duration / 1e6
        self.W, self.H = canvas
        self.img = self.render(k)

    def render(self, k):
        seg, st = self.seg, self.seg.style
        px = st.size * EM_PER_SIZE * self.W / 1080
        width_factor, caps_only = font_width(seg.font) if seg.font is not None else (None, False)
        font = _font(px)
        text = str(seg.text)
        if width_factor:  # match the curated font's measured width, so wrapping and size read right
            probe = max(text.split("\n"), key=len) or "M"
            caps = probe.upper() == probe and not caps_only
            target = len(probe) * width_factor * st.size * self.W / 1080 * (1.15 if caps else 1.0)
            have = font.getlength(probe) or 1
            font = _font(px * max(0.4, min(2.5, target / have)))
            px = font.size if hasattr(font, "size") else px
        stroke = 0
        if seg.border is not None:
            stroke = max(1, int(round(px * seg.border.width * 0.6)))  # border.width is CapCut's 0-0.2
        lines = []
        limit = st.max_line_width * self.W if st.auto_wrapping else None
        for para in text.split("\n"):
            words, cur = para.split(" "), ""
            for w in words:
                trial = f"{cur} {w}".strip()
                if limit and cur and font.getlength(trial) + 2 * stroke > limit:
                    lines.append(cur)
                    cur = w
                else:
                    cur = trial
            lines.append(cur)
        gap = int(px * 0.25)
        boxes = [font.getbbox(l or " ", stroke_width=stroke) for l in lines]
        lh = max(b[3] - b[1] for b in boxes) + gap
        tw = int(max(b[2] - b[0] for b in boxes)) + 2
        th = lh * len(lines)
        pad = int(px * 0.35) if seg.background is not None else 0
        img = Image.new("RGBA", (tw + 2 * pad + 4, th + 2 * pad + 4), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        if seg.background is not None:
            bg = seg.background
            d.rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=int(bg.round_radius * img.height / 2),
                                fill=_rgb(bg.color, bg.alpha))
        fill = _rgb(st.color, st.alpha)
        sfill = _rgb(seg.border.color, seg.border.alpha) if seg.border is not None else None
        for i, (line, b) in enumerate(zip(lines, boxes)):
            w = b[2] - b[0]
            x = {0: 0, 1: (tw - w) / 2, 2: tw - w}.get(st.align, (tw - w) / 2) + pad + 2 - b[0]
            y = pad + 2 + i * lh - b[1]
            if seg.shadow is not None:
                off = max(1, int(px * seg.shadow.distance / 100))
                d.text((x + off, y + off), line, font=font, fill=_rgb(seg.shadow.color, seg.shadow.alpha * 0.8),
                       stroke_width=stroke, stroke_fill=_rgb(seg.shadow.color, seg.shadow.alpha * 0.8))
            d.text((x, y), line, font=font, fill=fill, stroke_width=stroke, stroke_fill=sfill)
        return img

    def draw(self, canvas, t):
        tr = _transform(self.seg, t - self.start)
        sx, sy = tr["sx"], tr["sy"]
        _place(canvas, self.img, tr, (self.img.width * sx, self.img.height * sy))

    def close(self):
        pass


# ---------- the render ----------
def collect(builder: Builder, canvas, fps):
    """Layers in CapCut's stacking order (main track first, texts on top), plus audio inputs."""
    layers, sounds, skipped = [], [], set()
    k = canvas[0] / builder.width
    for track in sorted(builder.script.tracks.values(), key=lambda tr: tr.render_index):
        kind = track.track_type.name
        for seg in track.segments:
            seg._kf = _kf(seg)
            if kind == "video":
                main = track.name == "main"
                layers.append(VideoLayer(seg, track.name, canvas, fps, main))
                if getattr(seg, "transition", None) is not None:
                    skipped.add("transitions")
                if getattr(seg, "mask", None) is not None:
                    skipped.add("masks")
                if seg.filters or seg.effects:
                    skipped.add("clip filters/effects")
                if seg.animations_instance is not None:
                    skipped.add("clip animations")
                vol = float(seg.volume)
                if vol > 0 and seg.material_instance.material_type != "photo" and _has_audio(seg.material_instance.path):
                    sounds.append((seg, vol))
            elif kind == "text":
                layers.append(TextLayer(seg, canvas, k))
                if seg.animations_instance is not None:
                    skipped.add("text animations")
                if seg.font is not None:
                    skipped.add("fonts (a stand-in bold font is used)")
            elif kind == "audio":
                if float(seg.volume) > 0:
                    sounds.append((seg, float(seg.volume)))
            elif kind in ("effect", "filter"):
                skipped.add(f"{kind} tracks")
            elif kind == "sticker":
                skipped.add("stickers")
    return layers, sounds, sorted(skipped)


def audio_args(sounds, total):
    """Extra ffmpeg inputs and a filter graph that mixes every audible segment onto the timeline."""
    inputs, chains, labels = [], [], []
    for i, (seg, vol) in enumerate(sounds, start=1):
        src = seg.source_timerange
        inputs += ["-ss", f"{src.start / 1e6:.4f}", "-t", f"{src.duration / 1e6:.4f}", "-i", seg.material_instance.path]
        start = seg.target_timerange.start / 1e6
        dur = seg.target_timerange.duration / 1e6
        f = [f"[{i}:a]aresample=44100", "aformat=channel_layouts=stereo"] + _atempo(seg.speed.speed)
        f.append("asetpts=PTS-STARTPTS")
        vpts = [(p[0], p[1]) for p in seg._kf.get("volume", [])]
        f.append(f"volume='{_vol_expr(vpts, vol)}':eval=frame")
        fade = getattr(seg, "fade", None)
        if fade is not None:
            if fade.in_duration:
                f.append(f"afade=t=in:st=0:d={fade.in_duration / 1e6:.3f}")
            if fade.out_duration:
                f.append(f"afade=t=out:st={max(0.0, dur - fade.out_duration / 1e6):.3f}:d={fade.out_duration / 1e6:.3f}")
        ms = int(round(start * 1000))
        f.append(f"adelay={ms}|{ms}")
        chains.append(",".join(f) + f"[a{i}]")
        labels.append(f"[a{i}]")
    if not labels:
        return [], None
    mix = (f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,"
           f"apad=whole_dur={total:.3f},atrim=0:{total:.3f}[aout]")  # a bare apad never ends
    return inputs, ";".join(chains + [mix])


def stamp(canvas: Image.Image, t: float, font):
    d = ImageDraw.Draw(canvas)
    txt = f"{LABEL}  {t:5.2f}s"
    pad = 4
    w = font.getlength(txt)
    h = font.size if hasattr(font, "size") else 12
    d.rectangle((0, canvas.height - h - 2 * pad, w + 2 * pad, canvas.height), fill=(0, 0, 0, 170))
    d.text((pad, canvas.height - h - pad - 1), txt, font=font, fill=(255, 210, 0, 255))


def sheet_times(builder: Builder, total, every):
    if every is None:
        every = max(0.5, math.ceil(total / 12 * 2) / 2)  # at most about 12 tiles, on half seconds
    ts = [round(i * every, 3) for i in range(int(total / every) + 1) if i * every < total]
    for c in builder.main_clips:  # and the middle of every main clip, so each shot appears
        ts.append(round((c["start"] + c["end"]) / 2, 3))
    out = []
    for t in sorted(set(ts)):
        if not out or t - out[-1] >= 0.2:
            out.append(t)
    return out


def clip_at(builder: Builder, t):
    for r in builder.timeline:
        if r["kind"] == "clip" and r["start"] <= t < r["end"]:
            return f"@{r['id']}" if r["id"] else r["what"]
    return ""


def contact_sheet(tiles, path: Path, canvas, title):
    cols = 4 if canvas[0] < canvas[1] else 3
    tw = 240 if canvas[0] < canvas[1] else 360
    th = int(round(tw * canvas[1] / canvas[0]))
    cap = 22
    rows = math.ceil(len(tiles) / cols)
    head = 54
    sheet = Image.new("RGB", (cols * tw + (cols + 1) * 6, head + rows * (th + cap + 6) + 6), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    f1, f2 = _font(18), _font(14)
    d.text((8, 6), f"{title}  -  {LABEL}", font=f1, fill=(255, 210, 0))
    d.text((8, 30), NOT_DRAWN, font=_font(11), fill=(200, 200, 200))
    for i, (t, who, img) in enumerate(tiles):
        r, c = divmod(i, cols)
        x = 6 + c * (tw + 6)
        y = head + r * (th + cap + 6)
        sheet.paste(img.convert("RGB").resize((tw, th), Image.BILINEAR), (x, y + cap))
        d.text((x + 2, y + 3), f"{t:.2f}s  {who}", font=f2, fill=(255, 255, 255))
    sheet.save(path, quality=88)


def render(spec_path: Path, out_dir: Path, size=960, fps=15, every=None) -> dict:
    spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    builder = Builder(spec, spec_path.parent, allow_pro=True)  # preview whatever the plan; the build checks Pro
    builder.build()
    if builder.errors:
        raise SpecError("the spec has problems (run build_draft.py --check):\n  - " + "\n  - ".join(builder.errors))
    k = size / max(builder.width, builder.height)
    canvas = (max(2, int(round(builder.width * k / 2)) * 2), max(2, int(round(builder.height * k / 2)) * 2))
    total = builder.main_end / 1e6
    layers, sounds, skipped = collect(builder, canvas, fps)
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4, jpg = out_dir / "preview.mp4", out_dir / "sheet.jpg"
    ain, agraph = audio_args(sounds, total)
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{canvas[0]}x{canvas[1]}",
           "-r", str(fps), "-i", "-", *ain]
    if agraph:
        cmd += ["-filter_complex", agraph, "-map", "0:v", "-map", "[aout]", "-c:a", "aac", "-b:a", "96k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
            "-metadata", f"title={LABEL} of {spec_path.name}", "-metadata", f"comment={NOT_DRAWN}",
            "-t", f"{total:.3f}", "-movflags", "+faststart", str(mp4)]
    # stderr goes to a file: a pipe nobody reads until the end can fill up and stall ffmpeg (and us)
    log = tempfile.TemporaryFile()
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
    want = sheet_times(builder, total, every)
    tiles, wi = [], 0
    label_font = _font(max(10, canvas[0] // 36))
    n = max(1, int(math.ceil(total * fps - 1e-6)))
    try:
        for i in range(n):
            t = i / fps
            frame = Image.new("RGBA", canvas, (0, 0, 0, 255))
            for layer in layers:
                if layer.start <= t < layer.end:
                    layer.draw(frame, t)
                elif t >= layer.end:
                    layer.close()
            while wi < len(want) and want[wi] <= t + 1e-6:  # the first frame at or after each time
                tiles.append((t, clip_at(builder, t), frame.copy()))
                wi += 1
            stamp(frame, t, label_font)
            enc.stdin.write(frame.convert("RGB").tobytes())
        enc.stdin.close()
        code = enc.wait()
        log.seek(0)
        err = log.read().decode("utf-8", "replace")
        if code != 0:
            raise RuntimeError(f"ffmpeg failed: {err.strip()[-800:]}")
    finally:
        for layer in layers:
            layer.close()
        if enc.poll() is None:
            enc.kill()
        log.close()
    contact_sheet(tiles, jpg, canvas, spec.get("name", spec_path.stem))
    return {
        "status": "preview written (an approximation of the draft, not a CapCut render)",
        "preview": str(mp4), "sheet": str(jpg),
        "size": f"{canvas[0]}x{canvas[1]}@{fps}", "duration": round(total, 3), "frames": n,
        "sheet_times": [round(t, 2) for t, _, _ in tiles],
        "not_drawn": skipped,
        "note": f"{NOT_DRAWN}; cuts are hard cuts. Check timing, framing and text placement here, the look in CapCut.",
        "warnings": builder.warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", help="path to the edit spec JSON")
    ap.add_argument("--out", required=True, help="folder for preview.mp4 and sheet.jpg")
    ap.add_argument("--size", type=int, default=960, help="longer side of the preview in pixels (default 960)")
    ap.add_argument("--fps", type=int, default=15, help="preview frame rate (default 15)")
    ap.add_argument("--every", type=float, help="contact sheet: one tile every N seconds (default: about 16 tiles)")
    args = ap.parse_args()
    if args.size < 64 or args.fps < 1 or (args.every is not None and args.every <= 0):
        print("ERROR: --size must be at least 64, --fps at least 1, --every positive", file=sys.stderr)
        return 2
    spec_path = Path(args.spec).resolve()
    if not spec_path.is_file():
        print(f"ERROR: spec not found: {spec_path}", file=sys.stderr)
        return 2
    try:
        report = render(spec_path, Path(args.out).resolve(), args.size, args.fps, args.every)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot read spec: {e}", file=sys.stderr)
        return 2
    except SpecError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

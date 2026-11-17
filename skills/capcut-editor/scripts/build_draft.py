#!/usr/bin/env python3
"""Build an editable CapCut draft from a JSON edit spec.

  build_draft.py spec.json --check          # validate only, print the timeline
  build_draft.py spec.json                  # write the draft into CapCut's draft folder
  build_draft.py spec.json --overwrite      # replace a draft previously written by this tool
  build_draft.py spec.json --drafts-dir D   # write somewhere else

The spec format is documented in references/edit-spec.md.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import uuid
from pathlib import Path

from _common import SpecError, cc, find_drafts_dir, label, param_names, resolve

from pycapcut import assets as cc_assets
from pycapcut.script_file import ScriptFile

MARKER = ".cappus.json"
BLUR_LEVELS = {1: 0.0625, 2: 0.375, 3: 0.75, 4: 1.0}

VISUAL_KEYS = {
    "id", "src", "in", "out", "duration", "speed", "volume", "mute", "fit", "background", "transform",
    "keyframes", "motion", "intro", "outro", "combo", "filter", "effects", "mask", "blend", "chroma",
    "fade", "note",
}
MAIN_KEYS = VISUAL_KEYS | {"transition"}
OVERLAY_KEYS = VISUAL_KEYS | {"at", "end", "track"}
AUDIO_KEYS = {"id", "src", "at", "end", "in", "out", "duration", "speed", "volume", "fade", "effects",
              "keyframes", "duck", "track", "note"}
STYLE_KEYS = {
    "font", "size", "color", "opacity", "bold", "italic", "underline", "align", "vertical",
    "letter_spacing", "line_spacing", "wrap", "x", "y", "scale", "rotation", "stroke", "shadow",
    "background", "intro", "outro", "loop", "effect_id", "bubble",
}
TEXT_KEYS = STYLE_KEYS | {"text", "at", "end", "duration", "track", "style", "keyframes", "note"}
CAPTION_KEYS = {"srt", "cues", "words", "max_words", "max_chars", "max_gap", "uppercase", "offset",
                "style", "track", "min_duration"}
FX_KEYS = {"name", "at", "end", "duration", "params", "track", "note"}
FILTER_KEYS = {"name", "at", "end", "duration", "intensity", "track", "note"}
STICKER_KEYS = {"resource_id", "at", "end", "duration", "transform", "track", "keyframes", "note"}
TOP_KEYS = {"name", "width", "height", "fps", "allow_pro", "styles", "video", "overlays", "audio",
            "texts", "captions", "effects", "filters", "stickers", "note"}

KF_PROPS = {
    "x": cc.KeyframeProperty.position_x,
    "y": cc.KeyframeProperty.position_y,
    "rotation": cc.KeyframeProperty.rotation,
    "scale": cc.KeyframeProperty.uniform_scale,
    "scale_x": cc.KeyframeProperty.scale_x,
    "scale_y": cc.KeyframeProperty.scale_y,
    "opacity": cc.KeyframeProperty.alpha,
    "saturation": cc.KeyframeProperty.saturation,
    "contrast": cc.KeyframeProperty.contrast,
    "brightness": cc.KeyframeProperty.brightness,
    "volume": cc.KeyframeProperty.volume,
}
TEXT_KF = {"x", "y", "scale", "rotation"}
MOTIONS = {"push_in", "pull_out", "pan_left", "pan_right", "pan_up", "pan_down"}

_REF = re.compile(r"^@([A-Za-z0-9_\-]+)(?:\.(start|end))?\s*(?:([+-])\s*([0-9.]+))?$")
_END = re.compile(r"^end\s*(?:([+-])\s*([0-9.]+))?$")
_TC = re.compile(r"^(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)$")


def us(seconds) -> int:
    return int(round(float(seconds) * 1_000_000))


def sec(micros: int) -> float:
    return round(micros / 1_000_000, 3)


def hex_rgb(value, ctx="color"):
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return tuple(float(v) for v in value)
    if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value.strip()):
        v = value.strip()
        return tuple(int(v[i:i + 2], 16) / 255 for i in (1, 3, 5))
    raise SpecError(f"{ctx} must be '#RRGGBB', got {value!r}")


def check_keys(item, allowed, ctx):
    if not isinstance(item, dict):
        raise SpecError(f"{ctx} must be an object, got {type(item).__name__}")
    unknown = [k for k in item if k not in allowed]
    if unknown:
        raise SpecError(f"{ctx}: unknown key(s) {unknown}. Allowed: {sorted(allowed)}")


def named(value, ctx):
    """Accept "name" or {"name": ..., ...}; return a dict."""
    if isinstance(value, str):
        return {"name": value}
    if isinstance(value, dict) and "name" in value:
        return value
    raise SpecError(f"{ctx} must be a name string or an object with \"name\"")


class Builder:
    def __init__(self, spec: dict, base_dir: Path, allow_pro: bool):
        check_keys(spec, TOP_KEYS, "spec")
        self.spec = spec
        self.base = base_dir
        self.allow_pro = bool(allow_pro or spec.get("allow_pro"))
        self.width = int(spec.get("width", 1080))
        self.height = int(spec.get("height", 1920))
        self.fps = int(spec.get("fps", 30))
        self.script = ScriptFile(self.width, self.height, self.fps)
        self.errors: list = []
        self.warnings: list = []
        self.pro_used: list = []
        self.used: dict = {}
        self.clips: dict = {}       # id -> (start_us, end_us)
        self.timeline: list = []
        self.main_end = 0
        self._vmats: dict = {}
        self._amats: dict = {}
        self._track_count: dict = {}
        self.styles = spec.get("styles", {}) or {}

    # ---------- helpers ----------
    def res(self, kind, name):
        member = resolve(kind, name, self.allow_pro)
        if getattr(member.value, "is_vip", False):
            self.pro_used.append(f"{kind}: {label(kind, member)}")
        self.used.setdefault(kind, set()).add(label(kind, member))
        return member

    def res_effect(self, name):
        try:
            return self.res("scene_effect", name)
        except SpecError as scene_err:
            try:
                return self.res("character_effect", name)
            except SpecError:
                raise scene_err

    def path(self, src, ctx) -> str:
        if not isinstance(src, str) or not src:
            raise SpecError(f"{ctx}: \"src\" (media file path) is required")
        p = Path(src)
        if not p.is_absolute():
            p = self.base / p
        if not p.is_file():
            raise SpecError(f"{ctx}: media file not found: {p}")
        return str(p.resolve())

    def vmat(self, src, ctx):
        p = self.path(src, ctx)
        if p not in self._vmats:
            try:
                mat = cc.VideoMaterial(p)
            except Exception as e:
                raise SpecError(f"{ctx}: cannot read '{p}' as video/image: {e}")
            self._fix_rotation(mat)
            self._vmats[p] = mat
        return self._vmats[p]

    @staticmethod
    def _fix_rotation(mat):
        """Phone footage is often stored sideways with a rotation flag; CapCut works in display size."""
        try:
            import pymediainfo
            info = pymediainfo.MediaInfo.parse(mat.path)
            rot = float(getattr(info.video_tracks[0], "rotation", 0) or 0) if info.video_tracks else 0
            if int(round(rot)) % 180 == 90:
                mat.width, mat.height = mat.height, mat.width
        except Exception:
            pass

    def amat(self, src, ctx):
        p = self.path(src, ctx)
        if p not in self._amats:
            try:
                self._amats[p] = cc.AudioMaterial(p)
            except Exception as e:
                raise SpecError(f"{ctx}: cannot read '{p}' as audio: {e}")
        return self._amats[p]

    def t(self, value, ctx) -> int:
        """Timeline time -> microseconds. Number of seconds, 'mm:ss.s', '@id', '@id.end-0.5', 'end'."""
        if isinstance(value, bool):
            raise SpecError(f"{ctx}: time must be a number or reference, got {value!r}")
        if isinstance(value, (int, float)):
            return us(value)
        if isinstance(value, str):
            s = value.strip()
            m = _REF.match(s)
            if m:
                cid, edge, sign, off = m.groups()
                if cid not in self.clips:
                    raise SpecError(f"{ctx}: reference '@{cid}' matches no clip id. Known ids: {sorted(self.clips)}")
                start, end = self.clips[cid]
                base = end if edge == "end" else start
                return base + (us(off) * (1 if sign == "+" else -1) if off else 0)
            m = _END.match(s)
            if m:
                sign, off = m.groups()
                return self.main_end + (us(off) * (1 if sign == "+" else -1) if off else 0)
            m = _TC.match(s)
            if m:
                h, mnt, sc = m.groups()
                return us(int(h or 0) * 3600 + int(mnt) * 60 + float(sc))
            try:
                return us(float(s))
            except ValueError:
                pass
        raise SpecError(f"{ctx}: cannot parse time {value!r} (use seconds, 'mm:ss', '@clipid', '@clipid.end-0.5', or 'end')")

    def span(self, item, ctx, default_dur=None):
        start = self.t(item.get("at", 0), f"{ctx}.at")
        if "end" in item:
            dur = self.t(item["end"], f"{ctx}.end") - start
        elif "duration" in item:
            d = item["duration"]
            if isinstance(d, str) and d.strip().startswith("@"):
                cid = d.strip()[1:]
                if cid not in self.clips:
                    raise SpecError(f"{ctx}.duration: '@{cid}' matches no clip id")
                dur = self.clips[cid][1] - self.clips[cid][0]
            else:
                dur = us(d)
        elif default_dur is not None:
            dur = default_dur
        else:
            raise SpecError(f"{ctx}: needs \"duration\" or \"end\"")
        if start < 0:
            raise SpecError(f"{ctx}: starts before 0 ({sec(start)}s)")
        if dur <= 0:
            raise SpecError(f"{ctx}: duration must be positive (got {sec(dur)}s)")
        return start, dur

    def place(self, ttype, base_name, timerange) -> str:
        """Find (or create) a track of this type where the timerange is free; auto-adds lanes."""
        i = 1
        while True:
            name = base_name if i == 1 else f"{base_name} {i}"
            track = self.script.tracks.get(name)
            if track is None:
                idx = self._track_count.get(ttype, 0)
                self._track_count[ttype] = idx + 1
                self.script.add_track(ttype, name, relative_index=idx)
                return name
            if track.track_type != ttype:
                raise SpecError(f"track name '{name}' is already used by a {track.track_type.name} track")
            if not any(s.target_timerange.overlaps(timerange) for s in track.segments):
                return name
            i += 1

    def register(self, item, kind, start, dur, track, desc):
        cid = item.get("id") if isinstance(item, dict) else None
        if cid:
            if not re.fullmatch(r"[A-Za-z0-9_\-]+", str(cid)):
                raise SpecError(f"id '{cid}' may only contain letters, digits, _ and -")
            if cid in self.clips:
                raise SpecError(f"duplicate id '{cid}'")
            self.clips[cid] = (start, start + dur)
        self.timeline.append({"kind": kind, "track": track, "id": cid, "start": sec(start),
                              "end": sec(start + dur), "what": desc})

    # ---------- video ----------
    def fit_scale(self, mat, fit) -> float:
        if fit in (None, "contain"):
            return 1.0
        if fit != "cover":
            raise SpecError(f"fit must be 'contain' or 'cover', got {fit!r}")
        kx, ky = self.width / mat.width, self.height / mat.height
        return max(kx, ky) / min(kx, ky)

    def clip_settings(self, tr, base, ctx):
        tr = tr or {}
        check_keys(tr, {"scale", "scale_x", "scale_y", "x", "y", "rotation", "opacity", "flip_h", "flip_v"},
                   f"{ctx}.transform")
        s = float(tr.get("scale", 1.0))
        return cc.ClipSettings(
            alpha=float(tr.get("opacity", 1.0)),
            flip_horizontal=bool(tr.get("flip_h", False)), flip_vertical=bool(tr.get("flip_v", False)),
            rotation=float(tr.get("rotation", 0.0)),
            scale_x=float(tr.get("scale_x", s)) * base, scale_y=float(tr.get("scale_y", s)) * base,
            transform_x=float(tr.get("x", 0.0)), transform_y=float(tr.get("y", 0.0)),
        )

    def source_range(self, c, mat_duration, is_photo, ctx):
        """Return (source_start, source_dur, speed)."""
        speed = float(c.get("speed", 1.0))
        if speed <= 0:
            raise SpecError(f"{ctx}: speed must be > 0")
        if is_photo:
            return 0, us(c.get("duration", 3.0)), 1.0
        tin = us(c.get("in", 0))
        if "out" in c:
            tout = us(c["out"])
        elif "duration" in c:
            tout = tin + int(round(us(c["duration"]) * speed))
        else:
            tout = mat_duration
        if tout > mat_duration:
            if tout - mat_duration > 100_000:
                raise SpecError(f"{ctx}: needs source up to {sec(tout)}s but the file is only {sec(mat_duration)}s long")
            tout = mat_duration
        if tin < 0 or tout <= tin:
            raise SpecError(f"{ctx}: invalid source range in={sec(tin)}s out={sec(tout)}s")
        return tin, tout - tin, speed

    def make_video(self, c, start, ctx, forced_dur=None):
        mat = self.vmat(c.get("src"), ctx)
        photo = mat.material_type == "photo"
        if forced_dur is not None and "out" not in c:
            c = dict(c, duration=forced_dur / 1_000_000)
        tin, sdur, speed = self.source_range(c, mat.duration, photo, ctx)
        base = self.fit_scale(mat, c.get("fit"))
        seg = cc.VideoSegment(
            mat, cc.Timerange(start, int(round(sdur / speed))),
            source_timerange=cc.Timerange(tin, sdur), speed=speed,
            volume=0.0 if c.get("mute") else float(c.get("volume", 1.0)),
            clip_settings=self.clip_settings(c.get("transform"), base, ctx),
        )
        seg._base = base
        seg._mat = mat
        return seg

    def keyframes(self, seg, kf, ctx, base=1.0, allowed=None):
        if not kf:
            return
        if not isinstance(kf, dict):
            raise SpecError(f"{ctx}.keyframes must be an object like {{\"scale\": [[0, 1.0], [2.5, 1.15]]}}")
        dur = seg.duration
        for prop, points in kf.items():
            if prop not in KF_PROPS or (allowed and prop not in allowed):
                raise SpecError(f"{ctx}.keyframes: unsupported property '{prop}'. Allowed: {sorted(allowed or KF_PROPS)}")
            if not isinstance(points, list) or len(points) < 2:
                raise SpecError(f"{ctx}.keyframes.{prop}: need at least two [time, value] points")
            for pt in points:
                if not (isinstance(pt, (list, tuple)) and len(pt) == 2):
                    raise SpecError(f"{ctx}.keyframes.{prop}: each point is [seconds_from_clip_start, value]")
                off = us(pt[0])
                if off < 0:
                    off += dur  # negative = measured back from the clip end
                off = max(0, min(dur, off))
                val = float(pt[1])
                if prop in ("scale", "scale_x", "scale_y"):
                    val *= base
                seg.add_keyframe(KF_PROPS[prop], off, val)

    def motion_keyframes(self, motion, dur, ctx) -> dict:
        m = motion if isinstance(motion, dict) else {"type": motion}
        check_keys(m, {"type", "amount"}, f"{ctx}.motion")
        kind, a = m.get("type"), float(m.get("amount", 0.12))
        if kind not in MOTIONS:
            raise SpecError(f"{ctx}.motion: unknown type {kind!r}. Options: {sorted(MOTIONS)}")
        d = dur / 1_000_000
        if kind == "push_in":
            return {"scale": [[0, 1.0], [d, 1.0 + a]]}
        if kind == "pull_out":
            return {"scale": [[0, 1.0 + a], [d, 1.0]]}
        s = [[0, 1.0 + a], [d, 1.0 + a]]
        if kind == "pan_left":
            return {"scale": s, "x": [[0, a], [d, -a]]}
        if kind == "pan_right":
            return {"scale": s, "x": [[0, -a], [d, a]]}
        if kind == "pan_up":
            return {"scale": s, "y": [[0, -a], [d, a]]}
        return {"scale": s, "y": [[0, a], [d, -a]]}

    def decorate_video(self, seg, c, ctx, is_main):
        dur = seg.duration
        if c.get("combo") and (c.get("intro") or c.get("outro")):
            raise SpecError(f"{ctx}: a combo animation cannot be combined with intro/outro (CapCut allows one or the other)")
        for key, kind in (("intro", "video_intro"), ("outro", "video_outro"), ("combo", "video_combo")):
            if c.get(key):
                a = named(c[key], f"{ctx}.{key}")
                check_keys(a, {"name", "duration"}, f"{ctx}.{key}")
                d = min(us(a["duration"]), dur) if "duration" in a else None
                seg.add_animation(self.res(kind, a["name"]), d)
        if c.get("filter"):
            f = named(c["filter"], f"{ctx}.filter")
            check_keys(f, {"name", "intensity"}, f"{ctx}.filter")
            seg.add_filter(self.res("filter", f["name"]), float(f.get("intensity", 100)))
        for i, e in enumerate(c.get("effects") or []):
            e = named(e, f"{ctx}.effects[{i}]")
            check_keys(e, {"name", "params"}, f"{ctx}.effects[{i}]")
            member = self.res_effect(e["name"])
            seg.add_effect(member, self.params(member, e.get("params"), f"{ctx}.effects[{i}]"))
        if c.get("mask"):
            m = c["mask"]
            check_keys(m, {"type", "x", "y", "size", "rotation", "feather", "invert", "width", "round"}, f"{ctx}.mask")
            mtype = self.res("mask", m.get("type", "circle"))
            kwargs = dict(center_x=float(m.get("x", 0)) * seg._mat.width / 2,
                          center_y=float(m.get("y", 0)) * seg._mat.height / 2,
                          size=float(m.get("size", 0.5)), rotation=float(m.get("rotation", 0)),
                          feather=float(m.get("feather", 0)), invert=bool(m.get("invert", False)))
            if mtype == cc.MaskType.矩形:
                kwargs["rect_width"] = float(m.get("width", m.get("size", 0.5)))
                kwargs["round_corner"] = float(m.get("round", 0))
            elif "width" in m or "round" in m:
                raise SpecError(f"{ctx}.mask: 'width' and 'round' only apply to the rectangle mask")
            seg.add_mask(mtype, **kwargs)
        if c.get("blend"):
            seg.set_mix_mode(self.res("blend", c["blend"]))
        if c.get("chroma"):
            ch = c["chroma"]
            check_keys(ch, {"color", "intensity", "shadow"}, f"{ctx}.chroma")
            rgb = hex_rgb(ch.get("color", "#00FF00"), f"{ctx}.chroma.color")
            color = "#" + "".join(f"{int(round(v * 255)):02x}" for v in rgb) + "ff"
            seg.add_chroma(color, float(ch.get("intensity", 20)), float(ch.get("shadow", 0)))
        if c.get("background") is not None:
            if not is_main:
                raise SpecError(f"{ctx}: background fill only works on main-track clips")
            bg = c["background"]
            if bg == "blur" or (isinstance(bg, dict) and "blur" in bg):
                level = bg["blur"] if isinstance(bg, dict) else 2
                if level not in BLUR_LEVELS:
                    raise SpecError(f"{ctx}.background.blur must be 1-4")
                seg.add_background_filling("blur", blur=BLUR_LEVELS[level])
            else:
                rgb = hex_rgb(bg, f"{ctx}.background")
                seg.add_background_filling("color", color="#" + "".join(f"{int(round(v * 255)):02X}" for v in rgb) + "FF")
        if c.get("fade"):
            fd = c["fade"]
            check_keys(fd, {"in", "out"}, f"{ctx}.fade")
            seg.add_fade(us(fd.get("in", 0)), us(fd.get("out", 0)))
        kf = dict(c.get("keyframes") or {})
        if c.get("motion"):
            for prop, pts in self.motion_keyframes(c["motion"], dur, ctx).items():
                if prop in kf:
                    raise SpecError(f"{ctx}: motion preset and keyframes both animate '{prop}'; keep only one")
                kf[prop] = pts
        self.keyframes(seg, kf, ctx, base=seg._base)

    def params(self, member, params, ctx):
        if params is None:
            return None
        names = [p.replace("effects_adjust_", "") for p in param_names(member)]
        if isinstance(params, dict):
            out = [None] * len(names)
            for k, v in params.items():
                key = k.replace("effects_adjust_", "")
                if key not in names:
                    raise SpecError(f"{ctx}: '{member.name}' has no parameter '{k}'. Parameters: {names or 'none'}")
                out[names.index(key)] = float(v)
            params = out
        if not isinstance(params, list) or len(params) > len(names):
            raise SpecError(f"{ctx}: '{member.name}' takes {len(names)} parameter(s) {names}; got {params!r}")
        for v in params:
            if v is not None and not 0 <= float(v) <= 100:
                raise SpecError(f"{ctx}: parameter values are 0-100 (CapCut slider scale), got {v}")
        return params

    def build_main(self):
        clips = self.spec.get("video")
        if not isinstance(clips, list) or not clips:
            raise SpecError("spec.video must be a non-empty list of clips (the main track)")
        track = self.place(cc.TrackType.video, "main", cc.Timerange(0, 1))
        segs, cursor = [], 0
        for i, c in enumerate(clips):
            ctx = f"video[{i}]"
            try:
                check_keys(c, MAIN_KEYS, ctx)
                seg = self.make_video(c, cursor, ctx)
                segs.append((seg, c, ctx))
                self.register(c, "clip", cursor, seg.duration, track, Path(seg._mat.path).name)
                cursor += seg.duration
            except (SpecError, ValueError) as e:
                self.errors.append(str(e) if str(e).startswith(ctx) else f"{ctx}: {e}")
        self.main_end = cursor
        for n, (seg, c, ctx) in enumerate(segs):
            try:
                self.decorate_video(seg, c, ctx, True)
                if c.get("transition"):
                    if n == len(segs) - 1:
                        raise SpecError(f"{ctx}: a transition joins a clip to the NEXT one; the last clip has none (use an outro instead)")
                    tr = named(c["transition"], f"{ctx}.transition")
                    check_keys(tr, {"name", "duration"}, f"{ctx}.transition")
                    member = self.res("transition", tr["name"])
                    limit = min(seg.duration, segs[n + 1][0].duration) // 2
                    d = us(tr["duration"]) if "duration" in tr else member.value.default_duration
                    if d > limit:
                        self.warnings.append(f"{ctx}.transition shortened from {sec(d)}s to {sec(limit)}s (max is half the shorter neighbouring clip)")
                        d = limit
                    seg.add_transition(member, duration=d)
                self.script.add_segment(seg, track)
            except (SpecError, ValueError) as e:
                self.errors.append(str(e) if str(e).startswith(ctx) else f"{ctx}: {e}")

    def build_overlays(self):
        for i, c in enumerate(self.spec.get("overlays") or []):
            ctx = f"overlays[{i}]"
            try:
                check_keys(c, OVERLAY_KEYS, ctx)
                start = self.t(c.get("at", 0), f"{ctx}.at")
                forced = None
                if "end" in c:
                    forced = self.t(c["end"], f"{ctx}.end") - start
                    if forced <= 0:
                        raise SpecError(f"{ctx}: end must be after at")
                seg = self.make_video(c, start, ctx, forced)
                self.decorate_video(seg, c, ctx, False)
                track = self.place(cc.TrackType.video, c.get("track", "overlay"), seg.target_timerange)
                self.script.add_segment(seg, track)
                self.register(c, "overlay", start, seg.duration, track, Path(seg._mat.path).name)
            except (SpecError, ValueError) as e:
                self.errors.append(str(e) if str(e).startswith(ctx) else f"{ctx}: {e}")

    # ---------- audio ----------
    def build_audio(self):
        for i, a in enumerate(self.spec.get("audio") or []):
            ctx = f"audio[{i}]"
            try:
                check_keys(a, AUDIO_KEYS, ctx)
                mat = self.amat(a.get("src"), ctx)
                start = self.t(a.get("at", 0), f"{ctx}.at")
                speed = float(a.get("speed", 1.0))
                tin = us(a.get("in", 0))
                if "end" in a:
                    tout = tin + int(round((self.t(a["end"], f"{ctx}.end") - start) * speed))
                elif "duration" in a:
                    tout = tin + int(round(us(a["duration"]) * speed))
                elif "out" in a:
                    tout = us(a["out"])
                else:
                    tout = mat.duration
                if tout > mat.duration:
                    if "out" in a and tout - mat.duration > 100_000:
                        raise SpecError(f"{ctx}: out={sec(tout)}s is past the end of the file ({sec(mat.duration)}s)")
                    if tout - mat.duration > 100_000:
                        self.warnings.append(f"{ctx}: file ends at {sec(mat.duration)}s, so it stops {sec(int((tout - mat.duration) / speed))}s early (add another audio item to cover the rest)")
                    tout = mat.duration
                if tin < 0 or tout <= tin:
                    raise SpecError(f"{ctx}: invalid source range in={sec(tin)}s out={sec(tout)}s")
                vol = float(a.get("volume", 1.0))
                seg = cc.AudioSegment(mat, cc.Timerange(start, int(round((tout - tin) / speed))),
                                      source_timerange=cc.Timerange(tin, tout - tin), speed=speed, volume=vol)
                dur = seg.duration
                if a.get("fade"):
                    check_keys(a["fade"], {"in", "out"}, f"{ctx}.fade")
                    seg.add_fade(us(a["fade"].get("in", 0)), us(a["fade"].get("out", 0)))
                for j, e in enumerate(a.get("effects") or []):
                    e = named(e, f"{ctx}.effects[{j}]")
                    check_keys(e, {"name", "params"}, f"{ctx}.effects[{j}]")
                    try:
                        member = self.res("audio_effect", e["name"])
                    except SpecError as first:
                        try:
                            member = self.res("voice_effect", e["name"])
                        except SpecError:
                            raise first
                    seg.add_effect(member, self.params(member, e.get("params"), f"{ctx}.effects[{j}]"))
                points = []
                kf = a.get("keyframes") or {}
                if set(kf) - {"volume"}:
                    raise SpecError(f"{ctx}.keyframes: audio only supports 'volume'")
                for pt in kf.get("volume", []):
                    off = us(pt[0])
                    points.append((off + dur if off < 0 else off, float(pt[1])))
                if a.get("duck"):
                    dk = a["duck"]
                    check_keys(dk, {"ranges", "to", "ramp"}, f"{ctx}.duck")
                    low, ramp = float(dk.get("to", 0.2)) * vol, us(dk.get("ramp", 0.25))
                    for r in dk.get("ranges", []):
                        s0 = self.t(r[0], f"{ctx}.duck") - start
                        e0 = self.t(r[1], f"{ctx}.duck") - start
                        if e0 <= 0 or s0 >= dur:
                            continue
                        points += [(s0 - ramp, vol), (s0, low), (e0, low), (e0 + ramp, vol)]
                last = -1
                for off, val in sorted(points):
                    off = max(0, min(dur, off))
                    if off <= last:
                        continue
                    seg.add_keyframe(off, val)
                    last = off
                track = self.place(cc.TrackType.audio, a.get("track", "audio"), seg.target_timerange)
                self.script.add_segment(seg, track)
                self.register(a, "audio", start, dur, track, Path(mat.path).name)
            except (SpecError, ValueError) as e:
                self.errors.append(str(e) if str(e).startswith(ctx) else f"{ctx}: {e}")

    # ---------- text ----------
    def style_of(self, item, ctx) -> dict:
        ref = item.get("style")
        out = {}
        if isinstance(ref, str):
            if ref not in self.styles:
                raise SpecError(f"{ctx}: style '{ref}' is not defined in spec.styles (defined: {sorted(self.styles)})")
            out.update(self.styles[ref])
        elif isinstance(ref, dict):
            out.update(ref)
        check_keys(out, STYLE_KEYS, f"{ctx}.style")
        out.update({k: v for k, v in item.items() if k in STYLE_KEYS})
        return out

    def make_text(self, text, start, dur, st, ctx):
        align = {"left": 0, "center": 1, "right": 2}.get(st.get("align", "center"))
        if align is None:
            raise SpecError(f"{ctx}: align must be left, center or right")
        wrap = st.get("wrap", 0.82)
        style = cc.TextStyle(
            size=float(st.get("size", 8)), bold=bool(st.get("bold", False)), italic=bool(st.get("italic", False)),
            underline=bool(st.get("underline", False)), color=hex_rgb(st.get("color", "#FFFFFF"), f"{ctx}.color"),
            alpha=float(st.get("opacity", 1.0)), align=align, vertical=bool(st.get("vertical", False)),
            letter_spacing=int(st.get("letter_spacing", 0)), line_spacing=int(st.get("line_spacing", 0)),
            auto_wrapping=bool(wrap), max_line_width=float(wrap or 0.82),
        )
        border = shadow = background = None
        if st.get("stroke"):
            b = st["stroke"]
            check_keys(b, {"color", "width", "opacity"}, f"{ctx}.stroke")
            border = cc.TextBorder(alpha=float(b.get("opacity", 1)), color=hex_rgb(b.get("color", "#000000")),
                                   width=float(b.get("width", 40)))
        if st.get("shadow"):
            s = st["shadow"]
            check_keys(s, {"color", "opacity", "blur", "distance", "angle"}, f"{ctx}.shadow")
            shadow = cc.TextShadow(alpha=float(s.get("opacity", 0.8)), color=hex_rgb(s.get("color", "#000000")),
                                   diffuse=float(s.get("blur", 15)), distance=float(s.get("distance", 5)),
                                   angle=float(s.get("angle", -45)))
        if st.get("background"):
            g = st["background"]
            check_keys(g, {"color", "opacity", "radius", "style", "width", "height"}, f"{ctx}.background")
            hex_rgb(g.get("color", "#000000"), f"{ctx}.background.color")
            background = cc.TextBackground(color=g.get("color", "#000000"), style=int(g.get("style", 1)),
                                           alpha=float(g.get("opacity", 1)), round_radius=float(g.get("radius", 0)),
                                           height=float(g.get("height", 0.14)), width=float(g.get("width", 0.14)))
        sc = float(st.get("scale", 1.0))
        seg = cc.TextSegment(
            text, cc.Timerange(start, dur),
            font=self.res("font", st["font"]) if st.get("font") else None, style=style,
            clip_settings=cc.ClipSettings(transform_x=float(st.get("x", 0)), transform_y=float(st.get("y", 0)),
                                          scale_x=sc, scale_y=sc, rotation=float(st.get("rotation", 0))),
            border=border, background=background, shadow=shadow,
        )
        budget = dur
        for key, kind in (("intro", "text_intro"), ("outro", "text_outro")):
            if st.get(key):
                a = named(st[key], f"{ctx}.{key}")
                check_keys(a, {"name", "duration"}, f"{ctx}.{key}")
                member = self.res(kind, a["name"])
                d = us(a["duration"]) if "duration" in a else member.value.duration
                d = min(d, budget // 2 if st.get("intro") and st.get("outro") else budget)
                if d > 0:
                    seg.add_animation(member, d)
        if st.get("loop"):
            a = named(st["loop"], f"{ctx}.loop")
            seg.add_animation(self.res("text_loop", a["name"]))
        if st.get("effect_id"):
            seg.add_effect(str(st["effect_id"]))
        if st.get("bubble"):
            b = st["bubble"]
            check_keys(b, {"effect_id", "resource_id"}, f"{ctx}.bubble")
            seg.add_bubble(str(b["effect_id"]), str(b["resource_id"]))
        return seg

    def build_texts(self):
        for i, item in enumerate(self.spec.get("texts") or []):
            ctx = f"texts[{i}]"
            try:
                check_keys(item, TEXT_KEYS, ctx)
                if not isinstance(item.get("text"), str) or not item["text"].strip():
                    raise SpecError(f"{ctx}: \"text\" is required")
                start, dur = self.span(item, ctx)
                seg = self.make_text(item["text"], start, dur, self.style_of(item, ctx), ctx)
                self.keyframes(seg, item.get("keyframes"), ctx, allowed=TEXT_KF)
                track = self.place(cc.TrackType.text, item.get("track", "text"), seg.target_timerange)
                self.script.add_segment(seg, track)
                self.register(item, "text", start, dur, track, item["text"].replace("\n", " / ")[:40])
            except (SpecError, ValueError) as e:
                self.errors.append(str(e) if str(e).startswith(ctx) else f"{ctx}: {e}")

    def caption_cues(self, cap, ctx):
        sources = [k for k in ("srt", "cues", "words") if k in cap]
        if len(sources) != 1:
            raise SpecError(f"{ctx}: give exactly one of \"srt\", \"cues\" or \"words\"")
        cues = []
        if "srt" in cap:
            raw = Path(self.path(cap["srt"], ctx)).read_text(encoding="utf-8-sig")
            stamp = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
            for block in re.split(r"\r?\n\s*\r?\n", raw.strip()):
                lines = [ln for ln in block.splitlines() if ln.strip()]
                for n, ln in enumerate(lines):
                    m = stamp.search(ln)
                    if m:
                        g = [int(x) for x in m.groups()]
                        s0 = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                        e0 = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                        text = "\n".join(lines[n + 1:]).strip()
                        if text:
                            cues.append([s0, e0, re.sub(r"<[^>]+>", "", text)])
                        break
        elif "cues" in cap:
            for c in cap["cues"]:
                cues.append([float(c["start"]), float(c["end"]), str(c["text"])])
        else:
            max_words = int(cap.get("max_words", 3))
            max_chars = int(cap.get("max_chars", 18))
            max_gap = float(cap.get("max_gap", 0.6))
            cur = None
            for w in cap["words"]:
                word = str(w.get("word", w.get("text", ""))).strip()
                if not word:
                    continue
                s0, e0 = float(w["start"]), float(w["end"])
                new = (cur is None or len(cur[3]) >= max_words or s0 - cur[1] > max_gap
                       or len(" ".join(cur[3] + [word])) > max_chars or cur[3][-1][-1:] in ".?!,;:")
                if new:
                    cur = [s0, e0, "", [word]]
                    cues.append(cur)
                else:
                    cur[1] = e0
                    cur[3].append(word)
            for c in cues:
                c[2] = " ".join(c[3])
                del c[3]
        cues.sort(key=lambda c: c[0])
        offset = float(cap.get("offset", 0))
        min_d = float(cap.get("min_duration", 0.35))
        out = []
        for n, (s0, e0, text) in enumerate(cues):
            e0 = max(e0, s0 + min_d)
            if n + 1 < len(cues):
                e0 = min(e0, cues[n + 1][0])
            if e0 - s0 < 0.05 or s0 + offset < 0:
                continue
            if cap.get("uppercase"):
                text = text.upper()
            out.append((us(s0 + offset), us(e0 - s0), text))
        return out

    def build_captions(self):
        caps = self.spec.get("captions")
        if not caps:
            return
        for i, cap in enumerate(caps if isinstance(caps, list) else [caps]):
            ctx = f"captions[{i}]"
            try:
                check_keys(cap, CAPTION_KEYS, ctx)
                st = {"size": 9, "y": -0.6, "bold": True, "stroke": {"color": "#000000", "width": 40}}
                st.update(self.style_of({"style": cap.get("style")}, ctx))
                cues = self.caption_cues(cap, ctx)
                if not cues:
                    self.warnings.append(f"{ctx}: no caption cues found")
                base = cap.get("track", "captions")
                for start, dur, text in cues:
                    seg = self.make_text(text, start, dur, st, ctx)
                    self.script.add_segment(seg, self.place(cc.TrackType.text, base, seg.target_timerange))
                if cues:
                    self.timeline.append({"kind": "captions", "track": base, "id": None, "start": sec(cues[0][0]),
                                          "end": sec(cues[-1][0] + cues[-1][1]), "what": f"{len(cues)} cues"})
            except (SpecError, ValueError, KeyError) as e:
                self.errors.append(str(e) if str(e).startswith(ctx) else f"{ctx}: {e}")

    # ---------- global fx / filters / stickers ----------
    def build_fx(self):
        for i, e in enumerate(self.spec.get("effects") or []):
            ctx = f"effects[{i}]"
            try:
                check_keys(e, FX_KEYS, ctx)
                member = self.res_effect(e.get("name"))
                start, dur = self.span(e, ctx)
                rng = cc.Timerange(start, dur)
                track = self.place(cc.TrackType.effect, e.get("track", "fx"), rng)
                self.script.add_effect(member, rng, track, params=self.params(member, e.get("params"), ctx))
                self.register(e, "effect", start, dur, track, member.name)
            except (SpecError, ValueError) as err:
                self.errors.append(str(err) if str(err).startswith(ctx) else f"{ctx}: {err}")
        for i, f in enumerate(self.spec.get("filters") or []):
            ctx = f"filters[{i}]"
            try:
                check_keys(f, FILTER_KEYS, ctx)
                member = self.res("filter", f.get("name"))
                start, dur = self.span(f, ctx)
                rng = cc.Timerange(start, dur)
                track = self.place(cc.TrackType.filter, f.get("track", "look"), rng)
                self.script.add_filter(member, rng, track, float(f.get("intensity", 100)))
                self.register(f, "filter", start, dur, track, member.name)
            except (SpecError, ValueError) as err:
                self.errors.append(str(err) if str(err).startswith(ctx) else f"{ctx}: {err}")
        for i, s in enumerate(self.spec.get("stickers") or []):
            ctx = f"stickers[{i}]"
            try:
                check_keys(s, STICKER_KEYS, ctx)
                if not s.get("resource_id"):
                    raise SpecError(f"{ctx}: \"resource_id\" is required (see references/capcut-notes.md)")
                start, dur = self.span(s, ctx)
                seg = cc.StickerSegment(str(s["resource_id"]), cc.Timerange(start, dur),
                                        clip_settings=self.clip_settings(s.get("transform"), 1.0, ctx))
                self.keyframes(seg, s.get("keyframes"), ctx, allowed=TEXT_KF)
                track = self.place(cc.TrackType.sticker, s.get("track", "stickers"), seg.target_timerange)
                self.script.add_segment(seg, track)
                self.register(s, "sticker", start, dur, track, str(s["resource_id"]))
            except (SpecError, ValueError) as err:
                self.errors.append(str(err) if str(err).startswith(ctx) else f"{ctx}: {err}")

    def build(self):
        try:
            self.build_main()
        except SpecError as e:
            self.errors.append(str(e))
            return
        self.build_overlays()
        self.build_audio()
        self.build_texts()
        self.build_captions()
        self.build_fx()
        for track in self.script.tracks.values():  # CapCut expects each track in time order
            track.segments.sort(key=lambda s: s.target_timerange.start)
        total = self.script.duration
        if total > self.main_end + 50_000:
            self.warnings.append(
                f"content runs to {sec(total)}s but the main track ends at {sec(self.main_end)}s; "
                "the tail will show a black frame. Trim those items with \"end\": \"end\" or extend the main track.")

    def report(self) -> dict:
        return {
            "canvas": f"{self.width}x{self.height}@{self.fps}",
            "duration": sec(self.script.duration),
            "main_track_end": sec(self.main_end),
            "tracks": [f"{t.track_type.name}:{t.name} ({len(t.segments)})" for t in self.script.tracks.values()],
            "timeline": [
                f"{r['start']:7.2f} - {r['end']:7.2f}  {r['kind']:8} [{r['track']}] "
                + (f"@{r['id']} " if r["id"] else "") + r["what"]
                for r in sorted(self.timeline, key=lambda r: (r["start"], r["kind"]))
            ],
            "resources": {k: sorted(v) for k, v in self.used.items()},
            "pro_resources": sorted(set(self.pro_used)),
            "warnings": self.warnings,
        }


def write_draft(builder: Builder, drafts_dir: Path, name: str, overwrite: bool, spec_text: str) -> Path:
    if not name or re.search(r'[<>:"/\\|?*]', name):
        raise SpecError(f"draft name {name!r} is empty or has characters not allowed in a folder name")
    target = drafts_dir / name
    if target.exists():
        if not overwrite:
            raise SpecError(f"a draft named '{name}' already exists. Change spec.name, or pass --overwrite to replace it.")
        if not (target / MARKER).is_file():
            raise SpecError(f"'{name}' exists but was not created by this tool, so it will not be overwritten. Pick another name.")
        shutil.rmtree(target)
    target.mkdir(parents=True)
    content = builder.script.dumps()
    # Older CapCut builds read draft_content.json, newer ones draft_info.json; write both.
    (target / "draft_content.json").write_text(content, encoding="utf-8")
    (target / "draft_info.json").write_text(content, encoding="utf-8")
    with open(cc_assets.get_asset_path("DRAFT_META_TEMPLATE"), encoding="utf-8") as f:
        meta = json.load(f)
    now = int(time.time() * 1_000_000)
    meta.update({
        "draft_name": name, "draft_id": str(uuid.uuid4()).upper(),
        "draft_fold_path": target.as_posix(), "draft_root_path": drafts_dir.as_posix(),
        "tm_duration": builder.script.duration, "tm_draft_create": now, "tm_draft_modified": now,
    })
    (target / "draft_meta_info.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    (target / MARKER).write_text(spec_text, encoding="utf-8")
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", help="path to the edit spec JSON")
    ap.add_argument("--check", action="store_true", help="validate and print the timeline without writing")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing draft made by this tool")
    ap.add_argument("--drafts-dir", help="CapCut draft folder (auto-detected by default)")
    ap.add_argument("--allow-pro", action="store_true", help="permit CapCut Pro resources")
    args = ap.parse_args()

    spec_path = Path(args.spec).resolve()
    try:
        spec_text = spec_path.read_text(encoding="utf-8-sig")
        spec = json.loads(spec_text)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot read spec: {e}", file=sys.stderr)
        return 2

    try:
        builder = Builder(spec, spec_path.parent, args.allow_pro)
        builder.build()
    except SpecError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if builder.errors:
        print(f"{len(builder.errors)} problem(s) in the spec - nothing was written:", file=sys.stderr)
        for e in builder.errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    report = builder.report()
    if args.check:
        report["status"] = "valid (not written; run without --check to create the draft)"
    else:
        drafts = find_drafts_dir(args.drafts_dir)
        if args.drafts_dir and drafts is None:
            Path(args.drafts_dir).mkdir(parents=True, exist_ok=True)
            drafts = Path(args.drafts_dir)
        if drafts is None:
            drafts = spec_path.parent / "capcut_drafts"
            drafts.mkdir(exist_ok=True)
            report["warnings"].append(
                f"CapCut's draft folder was not found; wrote to {drafts}. Copy the draft folder into "
                "CapCut's draft location (CapCut > Settings > Drafts location).")
        try:
            target = write_draft(builder, drafts, str(spec.get("name", spec_path.stem)), args.overwrite, spec_text)
        except SpecError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        report["status"] = "draft written"
        report["draft"] = str(target)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

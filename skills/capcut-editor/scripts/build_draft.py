#!/usr/bin/env python3
"""Build an editable CapCut draft from a JSON edit spec.

  build_draft.py spec.json --check          # validate only, print the timeline
  build_draft.py spec.json                  # write the draft into CapCut's draft folder
  build_draft.py spec.json --overwrite      # replace a draft this tool wrote, if unchanged in CapCut
  build_draft.py spec.json --force          # replace it even though the user edited it in CapCut
  build_draft.py spec.json --drafts-dir D   # write somewhere else

A replaced draft is moved to ~/.cappus/backups/<name>-<time> (the newest 5 per name are kept).

CapCut Pro resources are allowed when, in order of precedence: --allow-pro / --free-only is
given, else the spec's "allow_pro", else the user's saved plan (tier.py pro). Otherwise free only.

The spec format is documented in references/edit-spec.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
import uuid
from pathlib import Path

from _common import (BACKUPS_KEPT, BUILD_FILE, MARKER, TIMELINE_ID, SpecError, backups_dir, cc, edit_check,
                     find_drafts_dir, label, param_names, resolve, signature_hash, timeline_signature, user_tier)

import looks as looks_mod
import motion
from _common import font_width
from pycapcut import assets as cc_assets
from pycapcut.script_file import ScriptFile

BLUR_LEVELS = {1: 0.0625, 2: 0.375, 3: 0.75, 4: 1.0}
# CapCut replaces this token with the draft's own folder when it reads a path.
DRAFT_DIR_TOKEN = "##_draftpath_placeholder_0E685133-18CE-45ED-8CB8-2904A212EC80_##"

VISUAL_KEYS = {
    "id", "src", "in", "out", "duration", "speed", "volume", "mute", "fit", "background", "transform",
    "keyframes", "motion", "intro", "outro", "combo", "filter", "effects", "mask", "blend", "chroma",
    "remove_bg", "fade", "enter", "exit", "drift", "adjust", "note",
}
MAIN_KEYS = VISUAL_KEYS | {"transition"}
OVERLAY_KEYS = VISUAL_KEYS | {"at", "end", "track"}
AUDIO_KEYS = {"id", "src", "at", "end", "in", "out", "duration", "speed", "volume", "fade", "effects",
              "keyframes", "duck", "track", "note"}
STYLE_KEYS = {
    "font", "size", "color", "opacity", "bold", "italic", "underline", "align", "vertical",
    "letter_spacing", "line_spacing", "wrap", "x", "y", "scale", "rotation", "stroke", "shadow",
    "background", "intro", "outro", "loop", "effect_id", "bubble", "enter", "exit", "drift",
    "fit_width", "size_max",
}
TEXT_KEYS = STYLE_KEYS | {"text", "at", "end", "duration", "track", "style", "keyframes", "echo", "note"}
ECHO_KEYS = {"count", "spacing", "stagger", "style", "color", "stroke"}
CAPTION_KEYS = {"transcript", "srt", "cues", "words", "source", "max_words", "max_chars", "max_gap",
                "uppercase", "punctuation", "offset", "style", "track", "min_duration", "note"}
NO_SPACE_LANGS = {"zh", "ja", "yue", "th", "lo", "my", "km", "bo"}  # written without spaces between words
CUE_BREAK = ".?!,;:。，、！？"
# Short words that should open a caption rather than end one (English and Indonesian).
DANGLING = {"a", "an", "the", "to", "of", "in", "on", "at", "for", "and", "or", "but", "with", "from", "by",
            "my", "your", "our", "their", "his", "her", "its", "di", "ke", "dari", "dan", "yang", "untuk",
            "atau", "dengan", "pada", "dalam", "si", "sang", "para", "agar", "karena", "tapi", "tetapi"}
_PUNCT = re.compile(r"(?<!\d)[.,!?;:…。，、！？]+|[.,!?;:…]+(?!\d)")
FX_KEYS = {"name", "at", "end", "duration", "params", "track", "note"}
FILTER_KEYS = {"name", "at", "end", "duration", "intensity", "track", "note"}
STICKER_KEYS = {"resource_id", "at", "end", "duration", "transform", "track", "keyframes", "note"}
TOP_KEYS = {"name", "width", "height", "fps", "allow_pro", "look", "brand", "styles", "video", "overlays", "audio",
            "texts", "captions", "effects", "filters", "stickers", "note"}
LIST_KEYS = ("video", "overlays", "audio", "texts", "effects", "filters", "stickers")

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

_REF = re.compile(r"^@([A-Za-z0-9_\-]+)(?:\.(start|end))?\s*(?:([+-])\s*(\d+(?:\.\d*)?|\.\d+))?$")
_END = re.compile(r"^end\s*(?:([+-])\s*(\d+(?:\.\d*)?|\.\d+))?$")
_TC = re.compile(r"^(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)$")


def us(seconds) -> int:
    return int(round(float(seconds) * 1_000_000))


def secs(value, ctx, lo=None, above=None) -> int:
    """A length of time in seconds from the spec -> microseconds, naming the field when it is not a number."""
    return us(num(value, ctx, lo=lo, above=above))


def sec(micros: int) -> float:
    return round(micros / 1_000_000, 3)


def hex_rgb(value, ctx="color"):
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return tuple(num(v, ctx, lo=0, hi=1) for v in value)
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


def matting_json(media_path: str) -> dict:
    """Video > Remove BG > Auto removal, as CapCut 9.8 saves it on the video material.

    flag 3 turns it on. path names the draft's mask cache, matting/<md5 of the media path>, which
    CapCut fills when it opens the draft. An empty path would make CapCut use one folder shared by
    every draft (User Data/2), so masks from different drafts could mix.
    """
    digest = hashlib.md5(media_path.replace("\\", "/").encode("utf-8")).hexdigest()
    return {
        "flag": 3, "path": DRAFT_DIR_TOKEN + "/matting\\" + digest,
        "custom_matting_id": str(uuid.uuid4()).upper(),
        "interactiveTime": [], "has_use_quick_brush": False, "strokes": [], "has_use_quick_eraser": False,
        "expansion": 0, "feather": 0, "reverse": False, "enable_matting_stroke": False,
        "is_clould": False, "mask_video_path": "", "cloud_product_fps": 0.0, "usage": "",
    }


def num(value, ctx, lo=None, hi=None, above=None) -> float:
    """A number from the spec, checked against the range CapCut accepts."""
    if isinstance(value, bool):
        raise SpecError(f"{ctx} must be a number, got {value!r}")
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise SpecError(f"{ctx} must be a number, got {value!r}")
    if v != v or v in (float("inf"), float("-inf")):
        raise SpecError(f"{ctx} must be a finite number, got {value!r}")
    if above is not None and v <= above:
        raise SpecError(f"{ctx} must be more than {above:g}, got {v:g}")
    if lo is not None and v < lo:
        raise SpecError(f"{ctx} must be at least {lo:g}, got {v:g}")
    if hi is not None and v > hi:
        raise SpecError(f"{ctx} must be at most {hi:g}, got {v:g}")
    return v


def as_list(value, ctx) -> list:
    """A list from the spec. A single name or object is taken as a one-item list."""
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        return [value]
    if isinstance(value, list):
        return value
    raise SpecError(f"{ctx} must be a list, got {type(value).__name__}")


def points(value, ctx, minimum=2) -> list:
    """Keyframe points: [[seconds, value], ...]."""
    if not isinstance(value, list):
        raise SpecError(f"{ctx} must be a list of [time, value] points, e.g. [[0, 1.0], [2.5, 0.3]], "
                        f"got {type(value).__name__}")
    if len(value) < minimum:
        raise SpecError(f"{ctx}: need at least {minimum} [time, value] point(s), e.g. [[0, 1.0], [2.5, 0.3]]")
    for pt in value:
        if not (isinstance(pt, (list, tuple)) and len(pt) == 2):
            raise SpecError(f"{ctx}: each point is [seconds_from_item_start, value], got {pt!r}")
    return value


# Value ranges per keyframe property (lo, hi, above).
KF_RANGES = {"opacity": (0, 1, None), "volume": (0, None, None), "scale": (None, None, 0),
             "scale_x": (None, None, 0), "scale_y": (None, None, 0), "saturation": (-1, 1, None),
             "contrast": (-1, 1, None), "brightness": (-1, 1, None)}
# Errors one spec item can raise; each is reported and the build moves on to the next item.
ITEM_ERRORS = (SpecError, ValueError, TypeError, KeyError, IndexError, AttributeError)
FPS_RATES = (24, 25, 30, 50, 60)


def named(value, ctx):
    """Accept "name" or {"name": ..., ...}; return a dict."""
    if isinstance(value, str):
        return {"name": value}
    if isinstance(value, dict) and "name" in value:
        return value
    raise SpecError(f"{ctx} must be a name string or an object with \"name\"")


class Builder:
    def __init__(self, spec: dict, base_dir: Path, allow_pro=None):
        if not isinstance(spec, dict):
            raise SpecError(f"the spec must be a JSON object ({{\"video\": [...], ...}}), got {type(spec).__name__}")
        check_keys(spec, TOP_KEYS, "spec")
        for key in LIST_KEYS:
            if spec.get(key) is not None and not isinstance(spec[key], list):
                raise SpecError(f"spec.{key} must be a list ([...]), got {type(spec[key]).__name__}")
        if spec.get("styles") is not None and not isinstance(spec["styles"], dict):
            raise SpecError("spec.styles must be an object of named styles")
        if spec.get("captions") is not None and not isinstance(spec["captions"], (dict, list)):
            raise SpecError("spec.captions must be an object, or a list of them")
        self.spec = spec
        self.base = base_dir
        if allow_pro is not None:
            self.allow_pro, self.pro_source = bool(allow_pro), "command line"
        elif "allow_pro" in spec:
            self.allow_pro, self.pro_source = bool(spec["allow_pro"]), "spec \"allow_pro\""
        else:
            tier, _ = user_tier()
            self.allow_pro = tier == "pro"
            self.pro_source = f"user plan: {tier}" if tier else "user plan not set (tier.py), free only"
        self.allow_unavailable = False  # check_resources.py turns this on to re-test blocked items
        self.errors: list = []
        self.warnings: list = []
        self.width = int(num(spec.get("width", 1080), "spec.width", lo=16, hi=8192))
        self.height = int(num(spec.get("height", 1920), "spec.height", lo=16, hi=8192))
        fps = num(spec.get("fps", 30), "spec.fps", above=0)
        # CapCut projects run at whole rates; 29.97 / 59.94 / 23.976 footage plays fine on the nearest one.
        self.fps = min(FPS_RATES, key=lambda r: abs(r - fps))
        if abs(self.fps - fps) > 0.01:
            self.warnings.append(f"spec.fps {fps:g} is not a CapCut project rate; using {self.fps} "
                                 f"(CapCut offers {', '.join(map(str, FPS_RATES))})")
        self.script = ScriptFile(self.width, self.height, self.fps)
        self.pro_used: list = []
        self.used: dict = {}
        self.clips: dict = {}       # id -> (start_us, end_us)
        self.plays: list = []       # audible media: (normcased path, src_start_us, src_dur_us, speed, start_us)
        self.timeline: list = []
        self.main_end = 0
        self._vmats: dict = {}
        self._amats: dict = {}
        self._track_count: dict = {}
        self.styles = self.resolve_styles(spec)
        self._fit_warned: set = set()

    # ---------- looks, motion presets, text fit ----------
    @staticmethod
    def resolve_styles(spec) -> dict:
        """The look's styles (if the spec names a look), overridden key by key by spec.styles."""
        own = spec.get("styles") or {}
        if "brand" in spec and not spec.get("look"):
            raise SpecError("spec.brand only applies together with spec.look")
        if not spec.get("look"):
            return own
        if not isinstance(spec["look"], str):
            raise SpecError("spec.look must be the name of a look (run looks.py to list them)")
        try:
            merged = looks_mod.styles(spec["look"], spec.get("brand"))
        except looks_mod.LookError as e:
            raise SpecError(str(e))
        for name, st in own.items():
            merged[name] = {**merged[name], **st} if isinstance(st, dict) and name in merged else st
        return merged

    def presets(self, item, kf, dur_us, rest, kind, ctx, width=0.0):
        """Add the item's "enter" / "exit" presets (motion.py) to its keyframes dict and return it."""
        dur = dur_us / 1_000_000
        for key, table, build in (("enter", motion.ENTER, "enter"), ("exit", motion.EXIT, "exit")):
            if not item.get(key):
                continue
            p = named(item[key], f"{ctx}.{key}")
            check_keys(p, {"name", "duration"}, f"{ctx}.{key}")
            name = p["name"]
            if name not in table or kind not in table[name][1]:
                usable = sorted(n for n, (_, kinds) in table.items() if kind in kinds)
                raise SpecError(f"{ctx}.{key}: no {key} preset '{name}' for {kind}s. Presets: {usable}")
            d = num(p.get("duration", table[name][0]), f"{ctx}.{key}.duration", above=0)
            d = min(d, dur / 2 if item.get("enter") and item.get("exit") else dur)
            if build == "enter":
                pts, window = motion.enter_points(name, d, rest, kind, width), (0.0, d)
            else:
                pts, window = motion.exit_points(name, d, dur, rest, kind), (dur - d, dur)
            for prop, added in pts.items():
                base = [[float(t) + dur if float(t) < 0 else float(t), v] for t, v in kf.get(prop, [])]
                kf[prop] = motion.merge(sorted(base), added, window, build)
        return kf

    def check_fit(self, text, st, member, ctx):
        """Warn once per item when a line is likely wider than the wrap width (it would wrap onto an
        extra line) or than the canvas. Widths are estimates from fonts.json, measured in CapCut."""
        if ctx in self._fit_warned:
            return
        k, caps_only = font_width(member) if member is not None else (2.6, False)
        size = float(st.get("size", 8)) * float(st.get("scale", 1.0))
        # CapCut letter spacing adds about 0.42 x size px per unit per character (measured in CapCut 9.8:
        # Cinzel "SUMMER" at size 26 / spacing 6 fit one line, "NEXT SUMMER" at 18 / 4 wrapped)
        spacing = float(st.get("letter_spacing", 0)) * 0.42 * size
        wrap = st.get("wrap", 0.82)
        limit = (0.82 if wrap is True else float(wrap or 0)) * self.width
        for line in str(text).split("\n"):
            caps = line.upper() == line and any(ch.isalpha() for ch in line) and not caps_only
            px = len(line) * (k * size * (1.15 if caps else 1.0) + spacing) * self.width / 1080
            if limit and px > limit:
                fit = size * limit / px
                self.warnings.append(f"{ctx}: '{line[:30]}' is about {int(px)} px wide at size {size:g}, wider than "
                                     f"the {int(limit)} px wrap width, so it wraps onto another line. Shorten it or "
                                     f"use size {int(fit * 10) / 10:g} or less.")
                self._fit_warned.add(ctx)
                return
            if not limit and px > 0.95 * self.width:
                self.warnings.append(f"{ctx}: '{line[:30]}' is about {int(px)} px wide at size {size:g} with wrapping "
                                     f"off, so it runs off the {self.width} px canvas.")
                self._fit_warned.add(ctx)
                return

    # ---------- helpers ----------
    def fail(self, ctx, e):
        """Record a problem with one spec item; the build carries on so all problems show at once."""
        msg = str(e)
        if not isinstance(e, (SpecError, ValueError)):
            msg = f"malformed value ({type(e).__name__}: {e}); check this item against references/edit-spec.md"
        self.errors.append(msg if msg.startswith(ctx) else f"{ctx}: {msg}")

    def res(self, kind, name):
        member = resolve(kind, name, self.allow_pro, self.allow_unavailable)
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

    def path(self, src, ctx, what="media file") -> str:
        if not isinstance(src, str) or not src:
            raise SpecError(f"{ctx}: \"src\" (media file path) is required")
        p = Path(src)
        if not p.is_absolute():
            p = self.base / p
        if not p.is_file():
            raise SpecError(f"{ctx}: {what} not found: {p}")
        return str(p.resolve())

    def heard(self, src, tin, sdur, speed, start, volume):
        """Remember where a media file is audible on the timeline (captions map speech through it)."""
        if volume > 0:
            self.plays.append((os.path.normcase(src), tin, sdur, speed, start))

    def vmat(self, src, ctx, remove_bg=False):
        """One material per file, plus a separate one for its Remove BG clips (CapCut keeps the
        Remove BG setting on the material, not on the clip)."""
        p = self.path(src, ctx)
        key = (p, remove_bg)
        if key not in self._vmats:
            try:
                mat = cc.VideoMaterial(p)
            except Exception as e:
                raise SpecError(f"{ctx}: cannot read '{p}' as video/image: {e}")
            self._fix_rotation(mat)
            if remove_bg:
                export, matting = mat.export_json, matting_json(mat.path)
                mat.export_json = lambda: {**export(), "matting": matting}
            self._vmats[key] = mat
        return self._vmats[key]

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
            return secs(value, ctx)
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
                return secs(float(s), ctx)
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
                dur = secs(d, f"{ctx}.duration")
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
        c = f"{ctx}.transform"
        s = num(tr.get("scale", 1.0), f"{c}.scale", above=0)
        return cc.ClipSettings(
            alpha=num(tr.get("opacity", 1.0), f"{c}.opacity", lo=0, hi=1),
            flip_horizontal=bool(tr.get("flip_h", False)), flip_vertical=bool(tr.get("flip_v", False)),
            rotation=num(tr.get("rotation", 0.0), f"{c}.rotation"),
            scale_x=num(tr.get("scale_x", s), f"{c}.scale_x", above=0) * base,
            scale_y=num(tr.get("scale_y", s), f"{c}.scale_y", above=0) * base,
            transform_x=num(tr.get("x", 0.0), f"{c}.x"), transform_y=num(tr.get("y", 0.0), f"{c}.y"),
        )

    def source_range(self, c, mat_duration, is_photo, ctx):
        """Return (source_start, source_dur, speed)."""
        speed = num(c.get("speed", 1.0), f"{ctx}.speed", lo=0.1, hi=100)
        if is_photo:
            return 0, secs(c.get("duration", 3.0), f"{ctx}.duration", above=0), 1.0
        tin = secs(c.get("in", 0), f"{ctx}.in", lo=0)
        if "out" in c:
            tout = secs(c["out"], f"{ctx}.out", lo=0)
        elif "duration" in c:
            tout = tin + int(round(secs(c["duration"], f"{ctx}.duration", above=0) * speed))
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
        remove_bg = c.get("remove_bg", False)
        if not isinstance(remove_bg, bool):
            raise SpecError(f"{ctx}.remove_bg must be true or false")
        if remove_bg:
            if not self.allow_pro:
                raise SpecError(
                    f"{ctx}: remove_bg uses CapCut's Auto removal, a CapCut Pro feature, and Pro is not enabled. "
                    "If the user has CapCut Pro, run `tier.py pro` or set \"allow_pro\": true in the spec. "
                    "Otherwise leave it out and tell the user the one-click way: select the clip > "
                    "Video > Remove BG > Auto removal.")
            self.pro_used.append("feature: remove_bg (Auto removal)")
        mat = self.vmat(c.get("src"), ctx, remove_bg)
        photo = mat.material_type == "photo"
        if forced_dur is not None and "out" not in c:
            c = dict(c, duration=forced_dur / 1_000_000)
        tin, sdur, speed = self.source_range(c, mat.duration, photo, ctx)
        base = self.fit_scale(mat, c.get("fit"))
        volume = 0.0 if c.get("mute") else num(c.get("volume", 1.0), f"{ctx}.volume", lo=0)
        seg = cc.VideoSegment(
            mat, cc.Timerange(start, int(round(sdur / speed))),
            source_timerange=cc.Timerange(tin, sdur), speed=speed, volume=volume,
            clip_settings=self.clip_settings(c.get("transform"), base, ctx),
        )
        seg._base = base
        seg._mat = mat
        if not photo:
            self.heard(self.path(c.get("src"), ctx), tin, sdur, speed, start, volume)
        return seg

    def keyframes(self, seg, kf, ctx, base=1.0, allowed=None):
        if not kf:
            return
        if not isinstance(kf, dict):
            raise SpecError(f"{ctx}.keyframes must be an object like {{\"scale\": [[0, 1.0], [2.5, 1.15]]}}")
        dur = seg.duration
        for prop, pts in kf.items():
            if prop not in KF_PROPS or (allowed and prop not in allowed):
                raise SpecError(f"{ctx}.keyframes: unsupported property '{prop}'. Allowed: {sorted(allowed or KF_PROPS)}")
            lo, hi, above = KF_RANGES.get(prop, (None, None, None))
            for pt in points(pts, f"{ctx}.keyframes.{prop}"):
                off = us(num(pt[0], f"{ctx}.keyframes.{prop} time"))
                if off < 0:
                    off += dur  # negative = measured back from the clip end
                off = max(0, min(dur, off))
                val = num(pt[1], f"{ctx}.keyframes.{prop} value", lo=lo, hi=hi, above=above)
                if prop in ("scale", "scale_x", "scale_y"):
                    val *= base
                seg.add_keyframe(KF_PROPS[prop], off, val)

    def motion_keyframes(self, motion, dur, ctx) -> dict:
        m = motion if isinstance(motion, dict) else {"type": motion}
        check_keys(m, {"type", "amount"}, f"{ctx}.motion")
        kind, a = m.get("type"), num(m.get("amount", 0.12), f"{ctx}.motion.amount", lo=0, hi=1)
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
                d = min(secs(a["duration"], f"{ctx}.{key}.duration", above=0), dur) if "duration" in a else None
                seg.add_animation(self.res(kind, a["name"]), d)
        if c.get("filter"):
            f = named(c["filter"], f"{ctx}.filter")
            check_keys(f, {"name", "intensity"}, f"{ctx}.filter")
            seg.add_filter(self.res("filter", f["name"]), num(f.get("intensity", 100), f"{ctx}.filter.intensity", lo=0, hi=100))
        for i, e in enumerate(as_list(c.get("effects"), f"{ctx}.effects")):
            e = named(e, f"{ctx}.effects[{i}]")
            check_keys(e, {"name", "params"}, f"{ctx}.effects[{i}]")
            member = self.res_effect(e["name"])
            seg.add_effect(member, self.params(member, e.get("params"), f"{ctx}.effects[{i}]"))
        if c.get("mask"):
            m = c["mask"]
            check_keys(m, {"type", "x", "y", "size", "rotation", "feather", "invert", "width", "round"}, f"{ctx}.mask")
            mtype = self.res("mask", m.get("type", "circle"))
            mc = f"{ctx}.mask"
            kwargs = dict(center_x=num(m.get("x", 0), f"{mc}.x") * seg._mat.width / 2,
                          center_y=num(m.get("y", 0), f"{mc}.y") * seg._mat.height / 2,
                          size=num(m.get("size", 0.5), f"{mc}.size", above=0),
                          rotation=num(m.get("rotation", 0), f"{mc}.rotation"),
                          feather=num(m.get("feather", 0), f"{mc}.feather", lo=0, hi=100),
                          invert=bool(m.get("invert", False)))
            if mtype == cc.MaskType.矩形:
                kwargs["rect_width"] = num(m.get("width", m.get("size", 0.5)), f"{mc}.width", above=0)
                kwargs["round_corner"] = num(m.get("round", 0), f"{mc}.round", lo=0, hi=100)
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
            seg.add_chroma(color, num(ch.get("intensity", 20), f"{ctx}.chroma.intensity", lo=0, hi=100),
                           num(ch.get("shadow", 0), f"{ctx}.chroma.shadow", lo=0, hi=100))
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
            seg.add_fade(us(num(fd.get("in", 0), f"{ctx}.fade.in", lo=0)),
                         us(num(fd.get("out", 0), f"{ctx}.fade.out", lo=0)))
        kf = dict(c.get("keyframes") or {})
        if c.get("motion"):
            tr0 = c.get("transform") or {}
            off = {"x": float(tr0.get("x", 0)), "y": float(tr0.get("y", 0))}
            sc0 = float(tr0.get("scale", 1.0))
            for prop, pts in self.motion_keyframes(c["motion"], dur, ctx).items():
                if prop in kf:
                    raise SpecError(f"{ctx}: motion preset and keyframes both animate '{prop}'; keep only one")
                # the move happens around the clip's own transform (a reframed or scaled clip keeps it)
                if prop in off:
                    pts = [[t, v + off[prop]] for t, v in pts]
                elif prop == "scale":
                    pts = [[t, v * sc0] for t, v in pts]
                kf[prop] = pts
        if c.get("adjust"):  # a constant color correction: brightness / contrast / saturation, -1..1
            adj = c["adjust"]
            check_keys(adj, {"brightness", "contrast", "saturation"}, f"{ctx}.adjust")
            for prop, v in adj.items():
                if prop in kf:
                    raise SpecError(f"{ctx}: adjust and keyframes both set '{prop}'; keep only one")
                v = num(v, f"{ctx}.adjust.{prop}", lo=-1, hi=1)
                kf[prop] = [[0, v], [dur / 1_000_000, v]]
        tr = c.get("transform") or {}
        s = float(tr.get("scale_x", tr.get("scale", 1.0)))
        if c.get("drift") and "scale" not in kf and not c.get("motion"):
            d = num(c["drift"], f"{ctx}.drift", lo=0, hi=1)
            kf["scale"] = [[0, s], [dur / 1_000_000, s * (1 + d)]]
        if c.get("enter") or c.get("exit"):
            rest = {"x": float(tr.get("x", 0)), "y": float(tr.get("y", 0)), "scale": s,
                    "opacity": float(tr.get("opacity", 1.0)), "rotation": float(tr.get("rotation", 0))}
            mat = seg._mat
            fitted = mat.width * min(self.width / mat.width, self.height / mat.height)  # px at scale 1, "contain"
            width = 2 * fitted * seg._base * s / self.width  # in half-canvas units
            self.presets(c, kf, dur, rest, "overlay", ctx, width)
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
                out[names.index(key)] = num(v, f"{ctx}.{k}")
            params = out
        if not isinstance(params, list) or len(params) > len(names):
            raise SpecError(f"{ctx}: '{member.name}' takes {len(names)} parameter(s) {names}; got {params!r}")
        for v in params:
            if v is not None and not 0 <= num(v, f"{ctx}: parameter") <= 100:
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
            except ITEM_ERRORS as e:
                self.fail(ctx, e)
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
                    d = (secs(tr["duration"], f"{ctx}.transition.duration", lo=0) if "duration" in tr
                         else member.value.default_duration)
                    if d > limit:
                        self.warnings.append(f"{ctx}.transition shortened from {sec(d)}s to {sec(limit)}s (max is half the shorter neighbouring clip)")
                        d = limit
                    seg.add_transition(member, duration=d)
                self.script.add_segment(seg, track)
            except ITEM_ERRORS as e:
                self.fail(ctx, e)

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
            except ITEM_ERRORS as e:
                self.fail(ctx, e)

    # ---------- audio ----------
    def build_audio(self):
        for i, a in enumerate(self.spec.get("audio") or []):
            ctx = f"audio[{i}]"
            try:
                check_keys(a, AUDIO_KEYS, ctx)
                mat = self.amat(a.get("src"), ctx)
                start = self.t(a.get("at", 0), f"{ctx}.at")
                speed = num(a.get("speed", 1.0), f"{ctx}.speed", lo=0.1, hi=100)
                tin = secs(a.get("in", 0), f"{ctx}.in", lo=0)
                if "end" in a:
                    tout = tin + int(round((self.t(a["end"], f"{ctx}.end") - start) * speed))
                elif "duration" in a:
                    tout = tin + int(round(secs(a["duration"], f"{ctx}.duration", above=0) * speed))
                elif "out" in a:
                    tout = secs(a["out"], f"{ctx}.out", lo=0)
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
                vol = num(a.get("volume", 1.0), f"{ctx}.volume", lo=0)
                seg = cc.AudioSegment(mat, cc.Timerange(start, int(round((tout - tin) / speed))),
                                      source_timerange=cc.Timerange(tin, tout - tin), speed=speed, volume=vol)
                self.heard(self.path(a.get("src"), ctx), tin, tout - tin, speed, start, vol)
                dur = seg.duration
                if a.get("fade"):
                    check_keys(a["fade"], {"in", "out"}, f"{ctx}.fade")
                    seg.add_fade(us(num(a["fade"].get("in", 0), f"{ctx}.fade.in", lo=0)),
                                 us(num(a["fade"].get("out", 0), f"{ctx}.fade.out", lo=0)))
                for j, e in enumerate(as_list(a.get("effects"), f"{ctx}.effects")):
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
                marks = []
                kf = a.get("keyframes") or {}
                if not isinstance(kf, dict):
                    raise SpecError(f"{ctx}.keyframes must be an object like {{\"volume\": [[0, 1.0], [2, 0.3]]}}")
                if set(kf) - {"volume"}:
                    raise SpecError(f"{ctx}.keyframes: audio only supports 'volume'")
                if "volume" in kf:
                    for pt in points(kf["volume"], f"{ctx}.keyframes.volume", minimum=1):
                        off = us(num(pt[0], f"{ctx}.keyframes.volume time"))
                        marks.append((off + dur if off < 0 else off,
                                       num(pt[1], f"{ctx}.keyframes.volume value", lo=0)))
                if a.get("duck"):
                    dk = a["duck"]
                    check_keys(dk, {"ranges", "to", "ramp"}, f"{ctx}.duck")
                    low = num(dk.get("to", 0.2), f"{ctx}.duck.to", lo=0) * vol
                    ramp = us(num(dk.get("ramp", 0.25), f"{ctx}.duck.ramp", lo=0))
                    ranges = dk.get("ranges", [])
                    if not isinstance(ranges, list):
                        raise SpecError(f"{ctx}.duck.ranges must be a list of [start, end] pairs")
                    for k, r in enumerate(ranges):
                        rc = f"{ctx}.duck.ranges[{k}]"
                        if not (isinstance(r, (list, tuple)) and len(r) == 2):
                            raise SpecError(f"{rc}: each range is [start, end], e.g. [\"@talk\", \"@talk.end\"]; got {r!r}")
                        s0 = self.t(r[0], rc) - start
                        e0 = self.t(r[1], rc) - start
                        if e0 <= 0 or s0 >= dur:
                            continue
                        marks += [(s0 - ramp, vol), (s0, low), (e0, low), (e0 + ramp, vol)]
                last = -1
                for off, val in sorted(marks):
                    off = max(0, min(dur, off))
                    if off <= last:
                        continue
                    seg.add_keyframe(off, val)
                    last = off
                track = self.place(cc.TrackType.audio, a.get("track", "audio"), seg.target_timerange)
                self.script.add_segment(seg, track)
                self.register(a, "audio", start, dur, track, Path(mat.path).name)
            except ITEM_ERRORS as e:
                self.fail(ctx, e)

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
        if wrap is True:
            wrap = 0.82
        wrap = num(wrap, f"{ctx}.wrap", above=0, hi=1) if wrap else 0
        style = cc.TextStyle(
            size=num(st.get("size", 8), f"{ctx}.size", above=0),
            bold=bool(st.get("bold", False)), italic=bool(st.get("italic", False)),
            underline=bool(st.get("underline", False)), color=hex_rgb(st.get("color", "#FFFFFF"), f"{ctx}.color"),
            alpha=num(st.get("opacity", 1.0), f"{ctx}.opacity", lo=0, hi=1), align=align,
            vertical=bool(st.get("vertical", False)),
            letter_spacing=int(num(st.get("letter_spacing", 0), f"{ctx}.letter_spacing")),
            line_spacing=int(num(st.get("line_spacing", 0), f"{ctx}.line_spacing")),
            auto_wrapping=bool(wrap), max_line_width=wrap or 0.82,
        )
        border = shadow = background = None
        if st.get("stroke"):
            b = st["stroke"]
            check_keys(b, {"color", "width", "opacity"}, f"{ctx}.stroke")
            border = cc.TextBorder(alpha=num(b.get("opacity", 1), f"{ctx}.stroke.opacity", lo=0, hi=1),
                                   color=hex_rgb(b.get("color", "#000000"), f"{ctx}.stroke.color"),
                                   width=num(b.get("width", 40), f"{ctx}.stroke.width", lo=0, hi=100))
        if st.get("shadow"):
            sh = st["shadow"]
            check_keys(sh, {"color", "opacity", "blur", "distance", "angle"}, f"{ctx}.shadow")
            shadow = cc.TextShadow(alpha=num(sh.get("opacity", 0.8), f"{ctx}.shadow.opacity", lo=0, hi=1),
                                   color=hex_rgb(sh.get("color", "#000000"), f"{ctx}.shadow.color"),
                                   diffuse=num(sh.get("blur", 15), f"{ctx}.shadow.blur", lo=0, hi=100),
                                   distance=num(sh.get("distance", 5), f"{ctx}.shadow.distance", lo=0, hi=100),
                                   angle=num(sh.get("angle", -45), f"{ctx}.shadow.angle", lo=-180, hi=180))
        if st.get("background"):
            g = st["background"]
            check_keys(g, {"color", "opacity", "radius", "style", "width", "height"}, f"{ctx}.background")
            hex_rgb(g.get("color", "#000000"), f"{ctx}.background.color")
            background = cc.TextBackground(
                color=g.get("color", "#000000"), style=int(num(g.get("style", 1), f"{ctx}.background.style", lo=1, hi=2)),
                alpha=num(g.get("opacity", 1), f"{ctx}.background.opacity", lo=0, hi=1),
                round_radius=num(g.get("radius", 0), f"{ctx}.background.radius", lo=0, hi=1),
                height=num(g.get("height", 0.14), f"{ctx}.background.height", lo=0, hi=1),
                width=num(g.get("width", 0.14), f"{ctx}.background.width", lo=0, hi=1))
        sc = num(st.get("scale", 1.0), f"{ctx}.scale", above=0)
        font = self.res("font", st["font"]) if st.get("font") else None
        self.check_fit(text, st, font, ctx)
        seg = cc.TextSegment(
            text, cc.Timerange(start, dur),
            font=font, style=style,
            clip_settings=cc.ClipSettings(transform_x=num(st.get("x", 0), f"{ctx}.x"),
                                          transform_y=num(st.get("y", 0), f"{ctx}.y"),
                                          scale_x=sc, scale_y=sc, rotation=num(st.get("rotation", 0), f"{ctx}.rotation")),
            border=border, background=background, shadow=shadow,
        )
        budget = dur
        for key, kind in (("intro", "text_intro"), ("outro", "text_outro")):
            if st.get(key):
                a = named(st[key], f"{ctx}.{key}")
                check_keys(a, {"name", "duration"}, f"{ctx}.{key}")
                member = self.res(kind, a["name"])
                d = secs(a["duration"], f"{ctx}.{key}.duration", above=0) if "duration" in a else member.value.duration
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

    def echo_items(self, item, ctx):
        """The item plus its echo copies: the same word repeated above and below it, each a little
        later, outlined (or in the echo's style), like a stamp hitting the screen several times."""
        echo = item.get("echo")
        if not echo:
            return [(ctx, item)]
        if echo is True:
            echo = {}
        check_keys(echo, ECHO_KEYS, f"{ctx}.echo")
        count = int(num(echo.get("count", 4), f"{ctx}.echo.count", lo=1, hi=8))
        spacing = num(echo.get("spacing", 0.2), f"{ctx}.echo.spacing", above=0, hi=1)
        stagger = num(echo.get("stagger", 0.08), f"{ctx}.echo.stagger", lo=0, hi=1)
        main = {k: v for k, v in item.items() if k != "echo"}
        out = [(ctx, main)]
        base_y = float(self.style_of(main, ctx).get("y", 0))
        start = self.t(main.get("at", 0), f"{ctx}.at")
        for n in range(count):
            step = n // 2 + 1
            copy = {k: v for k, v in main.items() if k not in ("exit", "keyframes", "style")}
            copy.update({k: v for k, v in self.style_of(main, ctx).items() if k not in ("exit", "intro", "outro")})
            copy["y"] = round(base_y + (step if n % 2 == 0 else -step) * spacing, 4)
            copy["at"] = round(start / 1e6 + stagger * (n + 1), 4)
            if "duration" in copy:
                copy["duration"] = max(0.05, float(copy["duration"]) - stagger * (n + 1))
            if echo.get("style"):
                copy["style"] = echo["style"]
                for k in self.styles.get(echo["style"], {}):
                    if k not in ("x", "y", "size", "fit_width", "font", "rotation"):
                        copy.pop(k, None)
            else:
                copy["color"] = echo.get("color", "#000000")
                copy["stroke"] = echo.get("stroke", {"color": "#FFFFFF", "width": 32})
            copy.pop("loop", None)
            out.append((f"{ctx}.echo[{n}]", copy))
        return out

    def fit_size(self, text, st, ctx):
        """The size that makes the longest line `fit_width` of the canvas wide, from fonts.json."""
        fit = num(st["fit_width"], f"{ctx}.fit_width", above=0, hi=1)
        member = self.res("font", st["font"]) if st.get("font") else None
        k, caps_only = font_width(member) if member is not None else (2.6, False)
        line = max(str(text).split("\n"), key=len)
        caps = line.upper() == line and any(ch.isalpha() for ch in line) and not caps_only
        per_char = k * (1.15 if caps else 1.0) + float(st.get("letter_spacing", 0)) * 0.42
        size = fit * 1080 / max(1, len(line)) / per_char
        return round(min(size, num(st.get("size_max", 48), f"{ctx}.size_max", above=0)), 1)

    def build_texts(self):
        expanded = []
        for i, item in enumerate(self.spec.get("texts") or []):
            try:
                check_keys(item, TEXT_KEYS, f"texts[{i}]")
                expanded += self.echo_items(item, f"texts[{i}]")
            except ITEM_ERRORS as e:
                self.fail(f"texts[{i}]", e)
        for ctx, item in expanded:
            try:
                check_keys(item, TEXT_KEYS, ctx)
                if not isinstance(item.get("text"), str) or not item["text"].strip():
                    raise SpecError(f"{ctx}: \"text\" is required")
                start, dur = self.span(item, ctx)
                st = self.style_of(item, ctx)
                if st.get("fit_width"):
                    st = dict(st, size=self.fit_size(item["text"], st, ctx))
                    st.setdefault("wrap", False)
                seg = self.make_text(item["text"], start, dur, st, ctx)
                kf = dict(item.get("keyframes") or {})
                sc = float(st.get("scale", 1.0))
                if st.get("drift") and "scale" not in kf:
                    d = num(st["drift"], f"{ctx}.drift", lo=0, hi=1)
                    kf["scale"] = [[0, sc], [dur / 1_000_000, sc * (1 + d)]]
                if st.get("enter") or st.get("exit"):
                    rest = {"x": float(st.get("x", 0)), "y": float(st.get("y", 0)), "scale": sc,
                            "opacity": 1.0, "rotation": float(st.get("rotation", 0))}
                    self.presets(st, kf, dur, rest, "text", ctx)
                self.keyframes(seg, kf, ctx, allowed=TEXT_KF)
                track = self.place(cc.TrackType.text, item.get("track", "text"), seg.target_timerange)
                self.script.add_segment(seg, track)
                self.register(item, "text", start, dur, track, item["text"].replace("\n", " / ")[:40])
            except ITEM_ERRORS as e:
                self.fail(ctx, e)

    def caption_plays(self, source, ctx):
        """Clips that make `source` audible, or None when the times are timeline seconds."""
        if not source:
            return None
        p = Path(source)
        p = (p if p.is_absolute() else self.base / p).resolve()
        plays = [pl for pl in self.plays if pl[0] == os.path.normcase(str(p))]
        if not plays:
            raise SpecError(f"{ctx}: no clip plays {p.name} with its sound on, so that speech is not on the "
                            "timeline. Add or unmute the clip, or set \"source\": null to read the caption "
                            "times as timeline seconds.")
        return plays

    @staticmethod
    def map_span(plays, s0, e0, whole):
        """Source seconds -> [(timeline start, end, clip index)]. Words go where their middle is."""
        if plays is None:
            return [(s0, e0, 0)]
        out = []
        for k, (_, tin, sdur, speed, at) in enumerate(plays):
            a, b = tin / 1e6, (tin + sdur) / 1e6
            lo, hi = max(s0, a), min(e0, b)
            if whole:
                if not a <= (s0 + e0) / 2 < b:
                    continue
            elif hi - lo < min(0.2, (e0 - s0) / 2):
                continue
            out.append((at / 1e6 + (lo - a) / speed, at / 1e6 + (hi - a) / speed, k))
        return out

    def caption_cues(self, cap, ctx):
        """Return ([(start_us, dur_us, text)], description)."""
        sources = [k for k in ("transcript", "words", "srt", "cues") if k in cap]
        if len(sources) != 1:
            raise SpecError(f"{ctx}: give exactly one of \"transcript\", \"words\", \"srt\" or \"cues\"")
        joiner, source, words, cues = " ", cap.get("source"), None, []
        if "transcript" in cap:
            tpath = self.path(cap["transcript"], ctx, "transcript")
            try:
                data = json.loads(Path(tpath).read_text(encoding="utf-8-sig"))
                words = list(data["words"])
            except (OSError, ValueError, KeyError, TypeError):
                raise SpecError(f"{ctx}: {tpath} is not a transcript made by transcribe.py")
            if "source" not in cap:
                source = data.get("source")
            joiner = "" if data.get("language") in NO_SPACE_LANGS else " "
        elif "words" in cap:
            words = cap["words"]
        elif "srt" in cap:
            raw = Path(self.path(cap["srt"], ctx, "SRT file")).read_text(encoding="utf-8-sig")
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
        else:
            for i, c in enumerate(cap["cues"]):
                cues.append([num(c["start"], f"{ctx}.cues[{i}].start", lo=0),
                             num(c["end"], f"{ctx}.cues[{i}].end", lo=0), str(c["text"])])

        plays = self.caption_plays(source, ctx)
        max_gap = num(cap.get("max_gap", 0.6), f"{ctx}.max_gap", lo=0)
        total = dropped = 0
        if words is not None:
            items, seen = [], set()
            for i, w in enumerate(words):
                word = str(w.get("word", w.get("text", ""))).strip()
                if not word:
                    continue
                total += 1
                spots = self.map_span(plays, num(w["start"], f"{ctx}.words[{i}].start"),
                                      num(w["end"], f"{ctx}.words[{i}].end"), True)
                dropped += not spots
                for s0, e0, k in spots:
                    if (round(s0, 2), word) not in seen:  # the same speech heard on two tracks
                        seen.add((round(s0, 2), word))
                        items.append((s0, e0, word, k))
            items.sort(key=lambda x: x[0])
            max_words = int(num(cap.get("max_words", 3), f"{ctx}.max_words", lo=1))
            max_chars = int(num(cap.get("max_chars", 18), f"{ctx}.max_chars", lo=1))
            groups, cur = [], None
            for s0, e0, word, k in items:
                hard = (cur is None or k != cur["k"] or s0 - cur["w"][-1][2] > max_gap
                        or cur["w"][-1][0][-1:] in CUE_BREAK)
                soft = not hard and (len(cur["w"]) >= max_words
                                     or len(joiner.join([x[0] for x in cur["w"]] + [word])) > max_chars)
                if hard or soft:
                    carry = []
                    if soft and max_words > 1 and len(cur["w"]) > 1 and cur["w"][-1][0].lower() in DANGLING:
                        carry = [cur["w"].pop()]  # "the slow way", not "videos the / slow way"
                    cur = {"k": k, "w": carry}
                    groups.append(cur)
                cur["w"].append((word, s0, e0))
            for n, g in enumerate(groups):
                s0, e0 = g["w"][0][1], g["w"][-1][2]
                nxt = groups[n + 1] if n + 1 < len(groups) else None
                if nxt and nxt["k"] == g["k"] and nxt["w"][0][1] - e0 < max_gap:
                    e0 = nxt["w"][0][1]  # hold the words through short pauses instead of flickering
                cues.append([s0, e0, joiner.join(x[0] for x in g["w"])])
        elif plays is not None:
            cues = [[s0, e0, text] for c0, c1, text in cues for s0, e0, _ in self.map_span(plays, c0, c1, False)]
        cues.sort(key=lambda c: c[0])
        offset = num(cap.get("offset", 0), f"{ctx}.offset")
        min_d = num(cap.get("min_duration", 0.35), f"{ctx}.min_duration", lo=0)
        out = []
        for n, (s0, e0, text) in enumerate(cues):
            e0 = max(e0, s0 + min_d)
            if n + 1 < len(cues):
                e0 = min(e0, cues[n + 1][0])
            if cap.get("punctuation") is False:
                text = re.sub(r"[ \t]{2,}", " ", _PUNCT.sub("", text)).strip()
            if e0 - s0 < 0.05 or s0 + offset < 0 or not text:
                continue
            if cap.get("uppercase"):
                text = text.upper()
            out.append((us(s0 + offset), us(e0 - s0), text))
        desc = f"{len(out)} cues"
        if plays is not None:
            desc += f", synced to {len(plays)} clip(s) of {Path(source).name}"
            if dropped:
                desc += f"; {dropped} of {total} words fall in parts that were cut"
        return out, desc

    def build_captions(self):
        caps = self.spec.get("captions")
        if not caps:
            return
        for i, cap in enumerate(caps if isinstance(caps, list) else [caps]):
            ctx = f"captions[{i}]"
            try:
                check_keys(cap, CAPTION_KEYS, ctx)
                st = {"size": 9, "y": -0.6, "bold": True, "stroke": {"color": "#000000", "width": 40}}
                default = "caption" if self.spec.get("look") and "caption" in self.styles else None
                st.update(self.style_of({"style": cap.get("style") or default}, ctx))
                cues, desc = self.caption_cues(cap, ctx)
                if not cues:
                    self.warnings.append(f"{ctx}: no caption cues found")
                base = cap.get("track", "captions")
                for start, dur, text in cues:
                    seg = self.make_text(text, start, dur, st, ctx)
                    self.script.add_segment(seg, self.place(cc.TrackType.text, base, seg.target_timerange))
                if cues:
                    self.timeline.append({"kind": "captions", "track": base, "id": None, "start": sec(cues[0][0]),
                                          "end": sec(cues[-1][0] + cues[-1][1]), "what": desc})
            except ITEM_ERRORS as e:
                self.fail(ctx, e)

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
            except ITEM_ERRORS as err:
                self.fail(ctx, err)
        for i, f in enumerate(self.spec.get("filters") or []):
            ctx = f"filters[{i}]"
            try:
                check_keys(f, FILTER_KEYS, ctx)
                member = self.res("filter", f.get("name"))
                start, dur = self.span(f, ctx)
                rng = cc.Timerange(start, dur)
                track = self.place(cc.TrackType.filter, f.get("track", "look"), rng)
                self.script.add_filter(member, rng, track,
                                       num(f.get("intensity", 100), f"{ctx}.intensity", lo=0, hi=100))
                self.register(f, "filter", start, dur, track, member.name)
            except ITEM_ERRORS as err:
                self.fail(ctx, err)
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
            except ITEM_ERRORS as err:
                self.fail(ctx, err)

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
        pro = sorted(set(self.pro_used))
        return {
            "canvas": f"{self.width}x{self.height}@{self.fps}",
            "pro_allowed": f"{'yes' if self.allow_pro else 'no'} ({self.pro_source})",
            "duration": sec(self.script.duration),
            "main_track_end": sec(self.main_end),
            "tracks": [f"{t.track_type.name}:{t.name} ({len(t.segments)})" for t in self.script.tracks.values()],
            "timeline": [
                f"{r['start']:7.2f} - {r['end']:7.2f}  {r['kind']:8} [{r['track']}] "
                + (f"@{r['id']} " if r["id"] else "") + r["what"]
                for r in sorted(self.timeline, key=lambda r: (r["start"], r["kind"]))
            ],
            "resources": {k: sorted(v) for k, v in self.used.items()},
            "pro_resources": pro,
            **({"pro_note": "Exporting this draft needs CapCut Pro on the account that exports it."}
               if pro else {}),
            "warnings": self.warnings,
        }


STAGING = ".cappus-replaced"  # next to CapCut's drafts folder, on the same drive, so moving a draft there is a rename
COPIED = "copied"  # written next to a staged draft once its backup copy is complete


def _unique(root: Path, name: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest, n = root / f"{name}-{stamp}", 2
    while dest.exists():
        dest, n = root / f"{name}-{stamp}-{n}", n + 1
    return dest


def _drop(box: Path):
    """Delete a staging folder, and the staging root too once nothing else is in it."""
    shutil.rmtree(box, ignore_errors=True)
    try:
        box.parent.rmdir()
    except OSError:
        pass


def stage_out(target: Path, name: str) -> Path:
    """Rename a draft folder out of CapCut's drafts folder to <staging>/<name>-<time>/<name>.

    A rename is all or nothing. On Windows it fails when a file in the draft is open in another
    program (CapCut, OneDrive, an antivirus scan, the search indexer), and then nothing has changed.
    shutil.move would instead fall back to copying and deleting file by file, which can leave a
    broken draft behind.
    """
    drafts = target.parent
    box = None
    for root in ((drafts.parent if drafts.parent != drafts else drafts) / STAGING, drafts / STAGING):
        try:
            root.mkdir(exist_ok=True)
            for old in root.iterdir():  # backed-up drafts whose files were still in use when they were deleted
                if (old / COPIED).is_file():
                    shutil.rmtree(old, ignore_errors=True)
            box = _unique(root, name)
            box.mkdir()
            break
        except OSError as e:  # the folder above the drafts folder is not writable: try inside it
            error = e
    if box is None:
        raise SpecError(f"could not make a folder to move the old '{name}' into ({error}); nothing was changed.")
    staged = box / name
    try:
        os.rename(target, staged)
    except OSError as e:
        _drop(box)
        raise SpecError(
            f"could not move the old '{name}' aside ({e.strerror or e}); nothing was changed. A program has "
            "a file in that draft open: CapCut (ask the user to go back to the home screen), or OneDrive, "
            "an antivirus scan or the search indexer (try again in a minute).")
    return staged


def back_up(staged: Path, name: str) -> str:
    """Move a staged draft to ~/.cappus/backups/<name>-<time>, keep the newest BACKUPS_KEPT per name,
    and return a sentence for the build report. If no backup can be made, the draft stays where
    stage_out() put it, and the sentence says where that is."""
    root = backups_dir()
    box = staged.parent
    try:
        root.mkdir(parents=True, exist_ok=True)
        dest = _unique(root, name)
        try:
            os.rename(staged, dest)  # same drive: instant
            shutil.rmtree(dest / "matting", ignore_errors=True)  # Remove BG masks: a cache CapCut rebuilds
        except OSError:  # another drive, or a file in it is still open: copy, leaving out that cache
            try:
                shutil.copytree(staged, dest, ignore=lambda d, names: ["matting"] if Path(d) == staged else [])
            except OSError:
                shutil.rmtree(dest, ignore_errors=True)
                raise
            (box / COPIED).touch()
            shutil.rmtree(staged, ignore_errors=True)
        os.utime(dest)  # the folder time becomes the backup time, which orders the pruning below
    except OSError as e:
        return (f"kept at {staged}, because copying it to {root} failed ({e}). Tell the user; to restore it, "
                "move that folder back into CapCut's drafts folder.")
    if not staged.exists():
        _drop(box)
    pattern = re.compile(re.escape(name) + r"-\d{8}-\d{6}(-\d+)?$")
    old = sorted((p for p in root.iterdir() if p.is_dir() and pattern.fullmatch(p.name)),
                 key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in old[BACKUPS_KEPT:]:
        shutil.rmtree(stale, ignore_errors=True)
    return (f"moved to {dest} (the newest {BACKUPS_KEPT} per draft are kept; Remove BG masks are left out "
            "and CapCut recomputes them)")


def write_draft(builder: Builder, drafts_dir: Path, name: str, overwrite: bool, spec_text: str,
                force: bool = False, backup: bool = True):
    """Write the draft folder. Returns (draft folder, report sentence about the replaced draft or None).

    Replacing an existing draft needs overwrite=True, and force=True as well when the user changed it
    in CapCut since it was built. The old draft is renamed out of the drafts folder first (all or
    nothing), then the new one is written, and only then is the old one moved or copied to
    backups_dir(). It is never deleted, except with backup=False (throwaway probe drafts).
    """
    if not name or re.search(r'[<>:"/\\|?*]', name):
        raise SpecError(f"draft name {name!r} is empty or has characters not allowed in a folder name")
    target = drafts_dir / name
    if target.exists():
        if not (overwrite or force):
            raise SpecError(f"a draft named '{name}' already exists. Change spec.name, or pass --overwrite to replace it.")
        if not (target / MARKER).is_file():
            raise SpecError(f"'{name}' exists but was not created by this tool, so it will not be overwritten. Pick another name.")
        if (target / ".locked").exists():
            raise SpecError(f"'{name}' is open in CapCut right now; it would overwrite this build when it saves. "
                            "Ask the user to go back to CapCut's home screen, then build again. (If CapCut is "
                            "closed, a stale .locked file is left in the draft folder.)")
        state = edit_check(target)
        if state["edited"] is not False and not force:
            what = "was changed in CapCut since it was built" if state["edited"] else "may have been changed in CapCut"
            changes = "; ".join(state.get("changes") or [])
            raise SpecError(
                f"'{name}' {what} ({state['how']}{': ' + changes if changes else ''}). Rebuilding would replace "
                "the user's changes. Ask them first: build under a new name to keep both, or rebuild with "
                f"--force, which first moves the current version to {backups_dir()}.")
    files = _draft_files(builder, drafts_dir, target, name, spec_text)  # everything that can fail on bad input
    staged = stage_out(target, name) if target.exists() else None
    try:
        target.mkdir(parents=True)
        for file_name, text in files.items():
            (target / file_name).parent.mkdir(parents=True, exist_ok=True)
            (target / file_name).write_text(text, encoding="utf-8")
    except BaseException as e:
        shutil.rmtree(target, ignore_errors=True)
        if staged is not None:
            try:
                os.rename(staged, target)
            except OSError:
                raise SpecError(f"could not write the new draft ({e}). The previous version is safe at {staged}; "
                                "move that folder back into CapCut's drafts folder.")
            _drop(staged.parent)
        if isinstance(e, OSError):
            raise SpecError(f"could not write the new draft ({e}); nothing was changed.")
        raise
    if staged is None:
        return target, None
    if not backup:
        _drop(staged.parent)
        return target, None
    return target, back_up(staged, name)


def _timelines(old: Path, content: str) -> tuple:
    """(content, extra files) for a draft replacing the one at old.

    CapCut 9 converts a draft to project form the first time it opens it: Timelines/project.json names
    the main timeline, whose files sit in Timelines/<id>/. While CapCut keeps running it remembers that
    form, and clicking a replacement draft without it does nothing until CapCut restarts (seen in 9.8).
    So a draft replacing one that has Timelines/project.json gets the same layout, under the same main
    timeline id. Anything unreadable there means no extra files: the draft then opens after a restart."""
    try:
        project = json.loads((old / "Timelines" / "project.json").read_bytes().decode("utf-8-sig"))
        main = project["main_timeline_id"]
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        return content, {}
    if not isinstance(main, str) or not TIMELINE_ID.fullmatch(main):
        return content, {}
    data = json.loads(content)
    if data.get("id") != main:
        data["id"] = main
        content = json.dumps(data, ensure_ascii=False, indent=4)
    now = int(time.time() * 1_000_000)
    timelines = project.get("timelines")
    tl_name = next((t.get("name") for t in timelines if isinstance(t, dict) and t.get("id") == main), None) \
        if isinstance(timelines, list) else None
    project.update({"main_timeline_id": main, "update_time": now, "timelines": [
        {"create_time": now, "id": main, "is_marked_delete": False,
         "name": tl_name if isinstance(tl_name, str) and tl_name else "Timeline 01", "update_time": now}]})
    return content, {
        f"Timelines/{main}/draft_content.json": content,
        f"Timelines/{main}/draft_info.json": content,
        "Timelines/project.json": json.dumps(project, ensure_ascii=False),
    }


def _draft_files(builder: Builder, drafts_dir: Path, target: Path, name: str, spec_text: str) -> dict:
    content, timelines = _timelines(target, builder.script.dumps())
    with open(cc_assets.get_asset_path("DRAFT_META_TEMPLATE"), encoding="utf-8") as f:
        meta = json.load(f)
    now = int(time.time() * 1_000_000)
    meta.update({
        "draft_name": name, "draft_id": str(uuid.uuid4()).upper(),
        "draft_fold_path": target.as_posix(), "draft_root_path": drafts_dir.as_posix(),
        "tm_duration": builder.script.duration, "tm_draft_create": now, "tm_draft_modified": now,
    })
    sig = timeline_signature(json.loads(content))
    return {
        # Older CapCut builds read draft_content.json, newer ones draft_info.json; write both.
        "draft_content.json": content,
        "draft_info.json": content,
        "draft_meta_info.json": json.dumps(meta, ensure_ascii=False),
        **timelines,
        BUILD_FILE: json.dumps({"built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "signature_sha256": signature_hash(sig), "signature": sig},
                               ensure_ascii=False, separators=(",", ":")),
        MARKER: spec_text,  # written last: its presence marks a complete draft made by this tool
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", help="path to the edit spec JSON")
    ap.add_argument("--check", action="store_true", help="validate and print the timeline without writing")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace an existing draft made by this tool, if it was not edited in CapCut")
    ap.add_argument("--force", action="store_true",
                    help="replace it even if it was edited in CapCut (only after the user agrees)")
    ap.add_argument("--drafts-dir", help="CapCut draft folder (auto-detected by default)")
    tier = ap.add_mutually_exclusive_group()
    tier.add_argument("--allow-pro", dest="allow_pro", action="store_const", const=True,
                      help="permit CapCut Pro resources for this build")
    tier.add_argument("--free-only", dest="allow_pro", action="store_const", const=False,
                      help="reject CapCut Pro resources for this build")
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
            target, saved = write_draft(builder, drafts, str(spec.get("name", spec_path.stem)), args.overwrite,
                                        spec_text, force=args.force)
        except SpecError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        report["status"] = "draft written"
        report["draft"] = str(target)
        if saved:
            report["previous_version"] = saved
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

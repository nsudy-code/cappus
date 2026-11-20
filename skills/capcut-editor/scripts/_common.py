"""Shared helpers: CapCut resource catalog lookup and draft-folder discovery."""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

try:
    import pycapcut as cc
except ImportError:  # pragma: no cover
    req = Path(__file__).resolve().parent.parent / "requirements.txt"
    sys.exit(
        "pycapcut is not installed for this Python interpreter.\n"
        f"Run:  {sys.executable} -m pip install -r \"{req}\""
    )

from _env import (backups_dir, config_path, draft_folder, find_drafts_dir,  # noqa: F401 (used by the scripts)
                  load_config, save_config, user_tier)

# Windows consoles default to a legacy code page; catalog names are often CJK.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class SpecError(Exception):
    """A problem in the edit spec that the author can fix."""


# kind -> (enum, human description)
KINDS = {
    "transition": (cc.TransitionType, "transition between two adjacent clips"),
    "video_intro": (cc.IntroType, "clip In animation"),
    "video_outro": (cc.OutroType, "clip Out animation"),
    "video_combo": (cc.GroupAnimationType, "clip Combo animation (whole clip, excludes In/Out)"),
    "text_intro": (cc.TextIntro, "text In animation"),
    "text_outro": (cc.TextOutro, "text Out animation"),
    "text_loop": (cc.TextLoopAnim, "text Loop animation"),
    "filter": (cc.FilterType, "color filter (look)"),
    "scene_effect": (cc.VideoSceneEffectType, "video effect (Effects > Video effects)"),
    "character_effect": (cc.VideoCharacterEffectType, "body effect (needs a person in frame)"),
    "audio_effect": (cc.AudioSceneEffectType, "audio voice/scene effect"),
    "voice_effect": (cc.ToneEffectType, "voice changer with sliders"),
    "font": (cc.FontType, "text font"),
    "mask": (cc.MaskType, "clip mask shape"),
    "blend": (cc.MixModeType, "overlay blend mode"),
}

_HERE = Path(__file__).resolve().parent
# aliases.json: English names for free resources. aliases_pro.json: curated CapCut Pro picks.
_ALIAS_FILES = (_HERE / "aliases.json", _HERE / "aliases_pro.json")
# Items CapCut no longer loads ("animation loss"); maintained with check_resources.py.
UNAVAILABLE_FILE = _HERE / "unavailable.json"
_aliases_cache = None
_unavailable_cache = None
_index_cache: dict = {}


def norm(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch not in " _-.'!·")


def aliases() -> dict:
    """kind -> {alias: CapCut name}, free aliases first (they win if a key appears twice)."""
    global _aliases_cache
    if _aliases_cache is None:
        merged: dict = {}
        for path in _ALIAS_FILES:
            if not path.is_file():
                continue
            with open(path, encoding="utf-8") as f:
                for kind, table in json.load(f).items():
                    if kind.startswith("_"):
                        continue
                    bucket = merged.setdefault(kind, {})
                    for alias, target in table.items():
                        bucket.setdefault(alias, target)
        fonts = merged.setdefault("font", {})
        for alias, info in curated_fonts().items():  # fonts.json: the curated fonts, with their aliases
            fonts.setdefault(alias, info["name"])
        _aliases_cache = merged
    return _aliases_cache


FONTS_FILE = _HERE / "fonts.json"
_fonts_cache = None
DEFAULT_FONT_WIDTH = 2.6  # canvas px per character per point of size, for fonts fonts.json does not list


def curated_fonts() -> dict:
    """alias -> {"name", "role", "moods", "width", "caps"?, "note"?} from fonts.json."""
    global _fonts_cache
    if _fonts_cache is None:
        try:
            _fonts_cache = json.loads(FONTS_FILE.read_text(encoding="utf-8")).get("fonts", {})
        except (OSError, json.JSONDecodeError):
            _fonts_cache = {}
    return _fonts_cache


def font_width(member) -> tuple:
    """(width factor, caps-only) for a font catalog member; the default when it is not curated."""
    for info in curated_fonts().values():
        if info.get("name") == getattr(member, "name", None):
            return float(info.get("width", DEFAULT_FONT_WIDTH)), bool(info.get("caps"))
    return DEFAULT_FONT_WIDTH, False


def unavailable(reload: bool = False) -> dict:
    """kind -> {catalog name: note} for items CapCut desktop fails to load."""
    global _unavailable_cache
    if _unavailable_cache is None or reload:
        try:
            with open(UNAVAILABLE_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = {}
        _unavailable_cache = {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}
    return _unavailable_cache


def unavailable_note(kind: str, member):
    """Why this item is blocked, or None when it is usable."""
    return unavailable().get(kind, {}).get(member.name)


# ---------- the user's CapCut plan (free or Pro), remembered per user ----------

def display_name(member) -> str:
    meta = member.value
    return getattr(meta, "name", None) or getattr(meta, "title", None) or member.name


def is_pro(member) -> bool:
    return bool(getattr(member.value, "is_vip", False))


def default_duration(member):
    """Default duration in seconds for animations/transitions, else None."""
    meta = member.value
    for attr in ("duration", "default_duration"):
        if hasattr(meta, attr):
            return getattr(meta, attr) / 1e6
    return None


def param_names(member) -> list:
    return [p.name for p in getattr(member.value, "params", [])]


def _index(kind: str):
    """Return (lookup: normalized key -> member, alias_of: member.name -> alias)."""
    if kind not in _index_cache:
        enum = KINDS[kind][0]
        lookup, alias_of = {}, {}
        for member in enum:
            lookup.setdefault(norm(member.name), member)
            lookup.setdefault(norm(display_name(member)), member)
        for alias, target in aliases().get(kind, {}).items():
            member = lookup.get(norm(target))
            if member is not None:
                lookup[norm(alias)] = member  # aliases win over raw names
                alias_of.setdefault(member.name, alias)
        _index_cache[kind] = (lookup, alias_of)
    return _index_cache[kind]


def alias_for(kind: str, member):
    return _index(kind)[1].get(member.name)


def label(kind: str, member) -> str:
    a = alias_for(kind, member)
    return f"{a} ({member.name})" if a else member.name


def suggest(kind: str, name: str, allow_pro: bool, n: int = 6) -> list:
    lookup, alias_of = _index(kind)
    pool = {}
    for member in KINDS[kind][0]:
        if (is_pro(member) and not allow_pro) or unavailable_note(kind, member):
            continue
        pool[norm(member.name)] = member
        if member.name in alias_of:
            pool[norm(alias_of[member.name])] = member
    key = norm(name)
    hits = [m for k, m in pool.items() if key and (key in k or k in key)]
    hits += [pool[k] for k in difflib.get_close_matches(key, list(pool), n=n, cutoff=0.6)]
    seen, out = set(), []
    for m in hits:
        if m.name not in seen:
            seen.add(m.name)
            out.append(label(kind, m))
    return out[:n]


def resolve(kind: str, name, allow_pro: bool = False, allow_unavailable: bool = False):
    """Look up a CapCut resource by alias or catalog name. Raises SpecError with suggestions.

    `name` may also be a catalog member itself (check_resources.py builds probes that way).
    """
    if kind not in KINDS:
        raise SpecError(f"unknown catalog kind '{kind}'")
    if isinstance(name, KINDS[kind][0]):
        member, name = name, name.name
    elif not isinstance(name, str) or not name.strip():
        raise SpecError(f"{kind} name must be a non-empty string, got {name!r}")
    else:
        member = _index(kind)[0].get(norm(name))
    if member is None:
        tips = suggest(kind, name, allow_pro)
        hint = f" Did you mean: {', '.join(tips)}?" if tips else ""
        raise SpecError(
            f"no {kind} named '{name}' in the CapCut catalog.{hint} "
            f"(search with: catalog.py {kind} <keyword>)"
        )
    if is_pro(member) and not allow_pro:
        tips = suggest(kind, name, False)
        hint = f" Free options: {', '.join(tips)}." if tips else ""
        raise SpecError(
            f"{kind} '{name}' is a CapCut Pro resource and Pro is not enabled; exporting it would need a "
            f"subscription.{hint} If the user has CapCut Pro, run `tier.py pro` (remembered for this user) "
            "or set \"allow_pro\": true in the spec."
        )
    note = unavailable_note(kind, member)
    if note and not allow_unavailable:
        tips = suggest(kind, name, allow_pro)
        hint = f" Alternatives: {', '.join(tips)}." if tips else ""
        raise SpecError(
            f"{kind} '{name}' is in the catalog but CapCut no longer loads it ({note}); the draft would show "
            f"it as missing (\"animation loss\").{hint} (search with: catalog.py {kind} <keyword>)"
        )
    return member


# ---------- did the user change a draft in CapCut? ----------

# Material kinds CapCut adds or rewrites on its own when it opens a draft; they say nothing about an edit.
_SIG_SKIP = {"speeds", "canvases", "placeholder_infos", "material_colors", "smart_relights", "multi_language_refs"}
# Audio tools CapCut attaches to clips in their off state when it saves a draft. They count only once
# the user turns one on. Field names are from CapCut 9.8 (MaterialRealtimeDenoise, MaterialLoudness,
# MaterialBeat in videoeditor.dll, and the off-state materials it writes).
_TOOL_KINDS = {"realtime_denoises", "loudnesses", "vocal_separations", "sound_channel_mappings", "beats"}


def _r(value, nd=4):
    """Round for the signature. CapCut saves floats with 6 decimals, so round to 6 first: otherwise a
    value on a rounding boundary flips (built -0.20375000000000001 is -0.2038, CapCut's -0.20375 is
    -0.2037) and a draft that was only opened reads as edited."""
    try:
        return round(round(float(value), 6), nd)
    except (TypeError, ValueError):
        return None


def _material_key(kind: str, m: dict):
    """What identifies a material from the user's point of view (ids change on every save)."""
    if kind in ("videos", "audios"):
        path = str(m.get("path") or "").replace("\\", "/")
        key = [kind, path.rsplit("/", 1)[-1].lower()]
        if kind == "videos":
            key.append(int((m.get("matting") or {}).get("flag") or 0))
        return key
    if kind == "texts":
        try:
            return [kind, json.loads(m.get("content") or "{}").get("text", "")]
        except (json.JSONDecodeError, AttributeError):
            return [kind, str(m.get("content", ""))]
    if kind == "material_animations":
        return [kind, sorted(str(a.get("name") or a.get("id") or "") for a in m.get("animations") or [])]
    if kind == "audio_fades":
        return [kind, m.get("fade_in_duration"), m.get("fade_out_duration")]
    if kind in ("masks", "common_mask"):  # CapCut 9 moves "masks" to "common_mask" with a new resource id
        return ["mask", str(m.get("resource_type") or m.get("name") or "")]
    if kind == "transitions":  # not the duration: CapCut shortens it on its own to fit short clips
        return [kind, str(m.get("effect_id") or m.get("name") or "")]
    return [kind, str(m.get("resource_id") or m.get("effect_id") or m.get("name") or m.get("type") or "")]


def _tool_state(kind: str, m: dict):
    """A key for an audio tool the user turned on, or None while it is off."""
    if kind == "realtime_denoises":
        return ["reduce noise", _r(m.get("denoise_mode")), _r(m.get("denoise_rate"))] if m.get("is_denoise") else None
    if kind == "loudnesses":
        return ["normalize loudness", _r(m.get("target_loudness"))] if m.get("enable") else None
    if kind == "vocal_separations":
        removed = m.get("removed_sounds") or []
        return ["isolate voice", m.get("choice"), json.dumps(removed, sort_keys=True)] if m.get("choice") or removed else None
    if kind == "sound_channel_mappings":
        on = m.get("type") not in (None, "", "none") or m.get("audio_channel_mapping")
        return ["channels", m.get("type"), m.get("audio_channel_mapping")] if on else None
    if kind == "beats":
        user = m.get("user_beats") or []
        on = user or m.get("enable_ai_beats")
        return ["beats", json.dumps(user, sort_keys=True), bool(m.get("enable_ai_beats"))] if on else None
    return None


SIG_VERSION = 2
# CapCut re-measures media when it opens a draft (an MP3 of 16.039 s became 16.067 s) and stretches a
# clip that plays its file to the end. Times within this slack count as equal.
_SLACK_US = 50_000


def timeline_signature(data: dict) -> dict:
    """The parts of a timeline a user changes when they edit it in CapCut: clips, their timing,
    transform, speed, volume, keyframes and attached animations / effects / filters / transitions,
    plus texts and stickers. Ids and the fields CapCut rewrites by itself when it merely opens a draft
    are left out, so opening, playing and closing a draft keeps the signature the same.

    Each item's position is its gap after the previous item on the same track, so a clip CapCut
    lengthens by a few milliseconds does not move everything after it. A clip that plays its media to
    the end records "end" instead of a length, since CapCut may measure that length differently."""
    by_id = {}
    for kind, items in (data.get("materials") or {}).items():
        if kind in _SIG_SKIP or not isinstance(items, list):
            continue
        for m in items:
            if isinstance(m, dict) and "id" in m:
                by_id[m["id"]] = (kind, m)
    tracks = []
    for t in data.get("tracks") or []:
        segs = []
        for s in t.get("segments") or []:
            tr, src = s.get("target_timerange") or {}, s.get("source_timerange") or {}
            kind, m = by_id.get(s.get("material_id"), ("?", {}))
            clip = s.get("clip") or {}
            refs = [by_id[ref] for ref in s.get("extra_material_refs") or [] if ref in by_id]
            extras = sorted(json.dumps(_material_key(k, x), ensure_ascii=False) for k, x in refs if k not in _TOOL_KINDS)
            tools = sorted(json.dumps(on, ensure_ascii=False)
                           for on in (_tool_state(k, x) for k, x in refs if k in _TOOL_KINDS) if on)
            keyframes = sorted(
                [k.get("property_type"), [[kf.get("time_offset"), [_r(v) for v in kf.get("values") or []]]
                                          for kf in k.get("keyframe_list") or []]]
                for k in s.get("common_keyframes") or [])
            start, dur = int(tr.get("start") or 0), int(tr.get("duration") or 0)
            src_part = None
            if src:
                s0, sd = int(src.get("start") or 0), int(src.get("duration") or 0)
                full = m.get("duration") if kind in ("videos", "audios") and m.get("type") != "photo" else None
                to_end = isinstance(full, (int, float)) and full > 0 and s0 + sd >= full - _SLACK_US
                src_part = [s0, "end" if to_end else sd]
            seg = {
                "t": round(start / 1e6, 2),  # for messages only; not compared
                "dur": None if src_part and src_part[1] == "end" else dur, "src": src_part,
                "speed": _r(s.get("speed", 1)), "volume": _r(s.get("volume", 1)),
                "visible": s.get("visible", True), "material": _material_key(kind, m) if m else None,
                "clip": [_r(clip.get("alpha")), (clip.get("flip") or {}).get("horizontal"),
                         (clip.get("flip") or {}).get("vertical"), _r(clip.get("rotation")),
                         _r((clip.get("scale") or {}).get("x")), _r((clip.get("scale") or {}).get("y")),
                         _r((clip.get("transform") or {}).get("x")), _r((clip.get("transform") or {}).get("y"))]
                if clip else None,
                "extras": extras, "keyframes": keyframes,
            }
            if tools:  # left out while all are off, so drafts built before this was added compare the same
                seg["tools"] = tools
            segs.append((start, dur, seg))
        out, prev_end = [], 0
        for start, dur, seg in sorted(segs, key=lambda x: (x[0], x[1])):
            seg["gap"] = start - prev_end
            prev_end = start + dur
            out.append(seg)
        tracks.append({"type": t.get("type"), "segments": out})
    canvas = data.get("canvas_config") or {}
    return {"v": SIG_VERSION, "canvas": [canvas.get("width"), canvas.get("height")],
            "fps": _r(data.get("fps"), 2), "tracks": tracks}


# Values (transform, opacity, speed, volume, keyframe values) this close are the same value: the signature
# keeps 4 decimals, so one rounding step apart is noise (signatures stored before _r rounded to 6 decimals
# first can differ by that much from a re-saved draft). Far below any change a user makes in CapCut.
_VALUE_SLACK = 2e-4


def _near(a, b, slack) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_near(x, y, slack) for x, y in zip(a, b))
    nums = (int, float)
    if isinstance(a, nums) and isinstance(b, nums) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) <= slack
    return a == b


def _close(a, b) -> bool:
    return _near(a, b, _SLACK_US)


_FIELD_NAMES = {"gap": "position", "dur": "length", "src": "trim", "clip": "transform",
                "extras": "effects/animations", "material": "media", "tools": "audio tools"}


def _segment_changes(x: dict, y: dict) -> list:
    out = []
    for k in sorted(set(x) | set(y)):
        if k == "t":
            continue
        a, b = x.get(k), y.get(k)
        if k in ("gap", "dur", "src"):
            same = _close(a, b)
        elif k in ("clip", "keyframes", "speed", "volume"):
            same = _near(a, b, _VALUE_SLACK)
        else:
            same = a == b
        if not same:
            out.append(_FIELD_NAMES.get(k, k))
    return out


def signature_hash(sig: dict) -> str:
    raw = json.dumps(sig, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


MARKER = ".cappus.json"           # copy of the spec; marks a draft this tool may overwrite
BUILD_FILE = ".cappus-build.json"  # timeline signature at build time, to detect edits made in CapCut
BACKUPS_KEPT = 5                   # per draft name


# CapCut's timeline ids. Also keeps a path such as "../x" in Timelines/project.json out of file names.
TIMELINE_ID = re.compile(r"[0-9A-Za-z-]{1,64}")


def timeline_files(folder: Path) -> list:
    """Every timeline file in a draft folder: the top-level pair and the copies under Timelines/<id>/."""
    return [p for name in ("draft_info.json", "draft_content.json")
            for p in [folder / name] + sorted(folder.glob(f"Timelines/*/{name}")) if p.is_file()]


def load_timeline(path: Path):
    """The parsed timeline, or None when the file is not plain JSON (an encrypted JianYing draft)."""
    try:
        return json.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def main_timeline_file(folder: Path):
    """Timelines/<id>/draft_content.json for the main timeline Timelines/project.json names, or None.

    Once CapCut 9 has opened a draft, that file holds the live timeline. CapCut 9.7.1 writes the
    top-level draft_info.json and Timelines/<id>/draft_info.json only when it first opens the draft,
    and never again, so after a copy, sync or restore resets file times, "newest" can pick one of those."""
    try:
        main = json.loads((folder / "Timelines" / "project.json").read_bytes().decode("utf-8-sig"))["main_timeline_id"]
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(main, str) or not TIMELINE_ID.fullmatch(main):
        return None
    path = folder / "Timelines" / main / "draft_content.json"
    return path if path.is_file() else None


def newest_timeline(folder: Path):
    """(path, data) of the draft's live timeline, or (None, None) when there is none: CapCut 9's main
    timeline when the draft has one, else the timeline file CapCut saved last. data is None when the
    file is not plain JSON (an encrypted JianYing draft, for example)."""
    files = timeline_files(folder)
    if not files:
        return None, None
    path = main_timeline_file(folder) or max(files, key=lambda f: f.stat().st_mtime)
    return path, load_timeline(path)


def describe_changes(old: dict, new: dict, limit: int = 8) -> list:
    """Short, human-readable differences between two timeline signatures; empty when they match."""
    out = []
    if old.get("canvas") != new.get("canvas") or old.get("fps") != new.get("fps"):
        out.append(f"canvas {old.get('canvas')}@{old.get('fps')} -> {new.get('canvas')}@{new.get('fps')}")
    ot, nt = old.get("tracks") or [], new.get("tracks") or []
    for i in range(max(len(ot), len(nt))):
        a = ot[i] if i < len(ot) else None
        b = nt[i] if i < len(nt) else None
        if a is None:
            out.append(f"track {i + 1} ({b['type']}) added with {len(b['segments'])} item(s)")
        elif b is None:
            out.append(f"track {i + 1} ({a['type']}) removed")
        elif a["type"] != b["type"]:
            out.append(f"track {i + 1}: {a['type']} -> {b['type']}")
        elif len(a["segments"]) != len(b["segments"]):
            out.append(f"track {i + 1} ({b['type']}): {len(a['segments'])} -> {len(b['segments'])} item(s)")
        else:
            for x, y in zip(a["segments"], b["segments"]):
                fields = _segment_changes(x, y)
                if fields:
                    out.append(f"track {i + 1} ({b['type']}) item at {y.get('t', 0):.2f}s: "
                               f"{', '.join(fields)} changed")
                if len(out) >= limit:
                    break
        if len(out) >= limit:
            out.append("...")
            break
    return out


def edit_check(folder: Path) -> dict:
    """Did the user change this tool-built draft in CapCut since it was built?

    Returns {"edited": True / False / None (cannot tell), "how": ..., "changes": [...]}.
    """
    files = timeline_files(folder)
    if not files:
        return {"edited": None, "how": "the draft has no timeline file"}
    readable = [(p, d) for p, d in ((p, load_timeline(p)) for p in files) if isinstance(d, dict)]
    if not readable:
        return {"edited": None, "how": f"{files[0].name} is not plain JSON"}
    try:
        stored = json.loads((folder / BUILD_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        stored = None
    old = stored.get("signature") if isinstance(stored, dict) else None
    if isinstance(old, dict) and old.get("v") == SIG_VERSION:
        # Every timeline file, not only the newest: CapCut leaves some of them as they were when it
        # first opened the draft, and file times mean nothing once a draft is copied, synced or restored.
        adjusted = False
        for path, data in sorted(readable, key=lambda pd: pd[0].stat().st_mtime, reverse=True):
            now = timeline_signature(data)
            if signature_hash(now) == stored.get("signature_sha256"):
                continue
            changes = describe_changes(old, now)
            if changes:
                return {"edited": True, "how": f"timeline differs from the build "
                                               f"({path.relative_to(folder).as_posix()})", "changes": changes}
            adjusted = True
        if adjusted:
            return {"edited": False, "how": "timeline matches the build (CapCut re-measured some timings or "
                                           "rounded some values)"}
        return {"edited": False, "how": "timeline matches the build"}
    # Built by cappus 0.4 or older, which kept no signature: compare file times. CapCut rewrites the
    # timeline when it merely opens a draft, so this also reports drafts that were only opened.
    try:
        built = (folder / MARKER).stat().st_mtime
    except OSError:
        return {"edited": None, "how": "no build record in the draft"}
    newest = max(p.stat().st_mtime for p in folder.rglob("*.json")
                 if p.name in ("draft_info.json", "draft_content.json"))
    return {"edited": newest - built > 5,
            "how": "file times (built by an older cappus, so opening the draft in CapCut also counts)"}

"""Shared helpers: CapCut resource catalog lookup and draft-folder discovery."""
from __future__ import annotations

import difflib
import json
import os
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
        _aliases_cache = merged
    return _aliases_cache


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

def config_path() -> Path:
    return Path(os.environ.get("CAPPUS_CONFIG") or (Path.home() / ".cappus" / "config.json"))


def load_config() -> dict:
    try:
        with open(config_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(cfg: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


def user_tier():
    """Return (tier, source): tier is "pro", "free" or None when nobody has said yet."""
    env = (os.environ.get("CAPPUS_TIER") or "").strip().lower()
    if env in ("pro", "free"):
        return env, "CAPPUS_TIER environment variable"
    saved = load_config().get("tier")
    if saved in ("pro", "free"):
        return saved, str(config_path())
    return None, "not set"


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


def find_drafts_dir(explicit=None):
    """Locate CapCut's draft folder. Returns a Path or None."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("CAPCUT_DRAFTS"):
        candidates.append(Path(os.environ["CAPCUT_DRAFTS"]))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft")
    home = Path.home()
    candidates.append(home / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft")
    candidates.append(home / "AppData" / "Local" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft")
    for c in candidates:
        if c.is_dir():
            return c
    return None

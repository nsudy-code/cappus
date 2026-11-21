#!/usr/bin/env python3
"""Series presets: one look for every episode of a series or brand ("dr-aisya", "kajian-subuh").

  presets.py                                   # the saved presets
  presets.py show dr-aisya                     # one preset in full
  presets.py save dr-aisya --look edu --accent "#14B8A6" --speaker "dr. Aisya" --role "Dokter Umum" \
                           --handle "@dr.aisya" --logo logo.png
  presets.py save dr-aisya --from-spec ep1.cut.json   # keep what an edit the user liked used
  presets.py save dr-aisya --from preset.json         # a preset written by hand (keys below)
  presets.py delete dr-aisya

Saved in ~/.cappus/presets/<name>.json (beside config.json; CAPPUS_CONFIG moves both). `save` on an
existing name updates it key by key, so one flag can change one thing.

Use it with "preset": "dr-aisya" in a spec, or cut_talk.py --preset dr-aisya. A preset holds:
  look, brand, fonts          as in a spec (the spec's own values win)
  styles                      style overrides, merged under the spec's own, key by key
  captions                    caption settings (max_words, uppercase, highlight, keywords, style, ...):
                              the spec's captions win; keywords words are added to the spec's
  handle                      {"text": "@dr.aisya", "x", "y", "style"}: on screen the whole video
  logo                        {"src": "C:/.../logo.png", "x", "y", "scale", "opacity"}: likewise
  speaker, role               the lower third cut_talk.py adds
  talk                        cut_talk.py defaults: punch, punch_hold, max_pause, pad, hook_first,
                              broll_every, broll_length, face_y, loudness (LUFS), denoise, zoom (mix/smooth/cut/off),
                              zoom_amount, drift; max_words is in captions
  music                       {"mood", "bpm"}: guidance for music.py
  description                 what the series is, for whoever picks it
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

from _env import config_path

KEYS = {"description", "look", "brand", "fonts", "styles", "captions", "handle", "logo", "speaker", "role",
        "talk", "music"}
CAPTION_KEYS = {"max_words", "max_chars", "max_gap", "uppercase", "punctuation", "style", "highlight",
                "keywords", "min_duration", "offset"}
TALK_KEYS = {"punch", "punch_hold", "max_pause", "pad", "hook_first", "broll_every", "broll_length", "face_y",
             "loudness", "denoise", "zoom", "zoom_amount", "drift"}
HANDLE_KEYS = {"text", "x", "y", "style"}
LOGO_KEYS = {"src", "x", "y", "scale", "opacity"}


class PresetError(Exception):
    pass


def presets_dir() -> Path:
    return config_path().parent / "presets"


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    if not s:
        raise PresetError(f"preset name {name!r} has no letters or digits")
    return s


def path_of(name: str) -> Path:
    return presets_dir() / f"{slug(name)}.json"


def names() -> list:
    d = presets_dir()
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


def load(name: str) -> dict:
    p = path_of(name)
    if not p.is_file():
        known = names()
        raise PresetError(f"no preset '{slug(name)}'" + (f". Saved presets: {', '.join(known)}" if known else
                                                          ". None saved yet: presets.py save <name> ..."))
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise PresetError(f"{p} is not valid JSON: {e}")
    return validate(data, slug(name))


def validate(data, name="preset") -> dict:
    if not isinstance(data, dict):
        raise PresetError(f"{name}: a preset is a JSON object")
    unknown = sorted(set(data) - KEYS - {"name"})
    if unknown:
        raise PresetError(f"{name}: unknown key(s) {unknown}. Allowed: {sorted(KEYS)}")
    if data.get("look"):
        import looks
        try:
            looks.colors(data["look"], data.get("brand"))
            looks.check_fonts(data.get("fonts"))
        except looks.LookError as e:
            raise PresetError(f"{name}: {e}")
    elif data.get("brand") or data.get("fonts"):
        raise PresetError(f"{name}: brand and fonts need a look")
    for key, allowed in (("captions", CAPTION_KEYS), ("talk", TALK_KEYS), ("handle", HANDLE_KEYS),
                         ("logo", LOGO_KEYS)):
        v = data.get(key)
        if v is None:
            continue
        if not isinstance(v, dict):
            raise PresetError(f"{name}.{key} must be an object")
        bad = sorted(set(v) - allowed)
        if bad:
            raise PresetError(f"{name}.{key}: unknown key(s) {bad}. Allowed: {sorted(allowed)}")
    if data.get("handle") and not str(data["handle"].get("text", "")).strip():
        raise PresetError(f"{name}.handle needs \"text\"")
    if data.get("logo"):
        src = data["logo"].get("src")
        if not src or not Path(src).is_absolute():
            raise PresetError(f"{name}.logo.src must be an absolute path (presets.py save --logo makes it one)")
    if data.get("styles") is not None and not isinstance(data["styles"], dict):
        raise PresetError(f"{name}.styles must be an object of named styles")
    return data


def _merge_captions(own, preset_caps):
    out = dict(preset_caps)
    out.update(own)
    pk, ok = preset_caps.get("keywords"), own.get("keywords")
    if pk and ok:  # the series' own words (its name, its topics) join the video's
        pw = pk if isinstance(pk, list) else pk.get("words", [])
        ow = ok if isinstance(ok, list) else ok.get("words", [])
        base = {} if isinstance(pk, list) else {k: v for k, v in pk.items() if k != "words"}
        if isinstance(ok, dict):
            base.update({k: v for k, v in ok.items() if k != "words"})
        out["keywords"] = dict(base, words=list(dict.fromkeys([*ow, *pw])))
    elif pk and not isinstance(pk, list) and not pk.get("words"):
        out.pop("keywords")  # only the color and size: nothing to color without the video's words
    return out


def apply(spec: dict) -> dict:
    """The spec with its "preset" filled in under it (the spec's own values win). Returns a copy."""
    name = spec.get("preset")
    if not name:
        return spec
    if not isinstance(name, str):
        raise PresetError("spec.preset must be the name of a saved preset (presets.py lists them)")
    p = load(name)
    out = copy.deepcopy(spec)
    for key in ("look", "brand", "fonts"):
        if key in p and key not in out:
            out[key] = copy.deepcopy(p[key])
    if p.get("styles"):
        styles = copy.deepcopy(p["styles"])
        for k, st in (out.get("styles") or {}).items():
            styles[k] = {**styles[k], **st} if isinstance(st, dict) and isinstance(styles.get(k), dict) else st
        out["styles"] = styles
    if p.get("captions") and out.get("captions"):
        caps = out["captions"]
        out["captions"] = ([_merge_captions(c, p["captions"]) for c in caps] if isinstance(caps, list)
                           else _merge_captions(caps, p["captions"]))
    if p.get("handle"):
        h = p["handle"]
        item = {"text": h["text"], "at": 0, "end": "end", "x": h.get("x", 0.0), "y": h.get("y", 0.82),
                "track": "brand", "note": f"preset {slug(name)}: handle"}
        if h.get("style"):
            item["style"] = h["style"]
        else:
            item.update(size=6, bold=True, color="#FFFFFF", opacity=0.9,
                        stroke={"color": "#000000", "width": 30})  # readable on sky and on shirts
        out["texts"] = [*(out.get("texts") or []), item]
    if p.get("logo"):
        lg = p["logo"]
        tf = {"x": lg.get("x", 0.78), "y": lg.get("y", 0.86), "scale": lg.get("scale", 0.14)}
        if "opacity" in lg:
            tf["opacity"] = lg["opacity"]
        out["overlays"] = [*(out.get("overlays") or []),
                           {"src": lg["src"], "at": 0, "end": "end", "fit": "contain", "transform": tf,
                            "track": "logo", "note": f"preset {slug(name)}: logo"}]
    del out["preset"]
    return out


def from_spec(spec: dict) -> dict:
    """What a spec the user liked used, as a preset: look, brand, fonts, styles, caption settings."""
    out = {k: copy.deepcopy(spec[k]) for k in ("look", "brand", "fonts", "styles") if spec.get(k)}
    caps = spec.get("captions")
    if isinstance(caps, list):
        caps = caps[0] if caps else None
    if isinstance(caps, dict):
        c = {k: copy.deepcopy(v) for k, v in caps.items() if k in CAPTION_KEYS}
        if isinstance(c.get("keywords"), dict):  # the words were that video's; keep the color and size
            c["keywords"] = {k: v for k, v in c["keywords"].items() if k != "words"}
        elif isinstance(c.get("keywords"), list):
            c.pop("keywords")
        if c:
            out["captions"] = c
    if isinstance(out.get("styles"), dict):  # a caption moved off one video's face is not the series' place
        cap = out["styles"].get("caption")
        if isinstance(cap, dict) and set(cap) == {"y"}:
            out["styles"].pop("caption")
        if not out["styles"]:
            out.pop("styles")
    return out


def save(name: str, update: dict) -> Path:
    p = path_of(name)
    data = {}
    if p.is_file():
        data = json.loads(p.read_text(encoding="utf-8"))
    for k, v in update.items():
        if isinstance(v, dict) and isinstance(data.get(k), dict):
            data[k] = {**data[k], **v}
        else:
            data[k] = v
    data.pop("name", None)
    validate(data, slug(name))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"name": slug(name), **data}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", choices=["list", "show", "save", "delete"], default="list")
    ap.add_argument("name", nargs="?")
    ap.add_argument("--from", dest="src", help="save: a preset JSON written by hand")
    ap.add_argument("--from-spec", help="save: take look, brand, fonts, styles and caption settings from a spec")
    ap.add_argument("--look")
    ap.add_argument("--accent", help="#RRGGBB, the brand color")
    ap.add_argument("--speaker")
    ap.add_argument("--role")
    ap.add_argument("--handle", help="@name shown small for the whole video")
    ap.add_argument("--logo", help="an image shown small for the whole video")
    ap.add_argument("--description")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    try:
        if args.action == "list":
            rows = []
            for n in names():
                try:
                    d = load(n)
                    rows.append({"name": n, "look": d.get("look"), "description": d.get("description", "")})
                except PresetError as e:
                    rows.append({"name": n, "error": str(e)})
            print(json.dumps({"folder": str(presets_dir()), "presets": rows}, ensure_ascii=False, indent=1))
            return 0
        if not args.name:
            ap.error(f"{args.action} needs a preset name")
        if args.action == "show":
            print(json.dumps(load(args.name), ensure_ascii=False, indent=1))
        elif args.action == "delete":
            p = path_of(args.name)
            if not p.is_file():
                raise PresetError(f"no preset '{slug(args.name)}'")
            p.unlink()
            print(json.dumps({"deleted": str(p)}))
        else:
            update = {}
            if args.src:
                update.update(json.loads(Path(args.src).read_text(encoding="utf-8")))
            if args.from_spec:
                update.update(from_spec(json.loads(Path(args.from_spec).read_text(encoding="utf-8"))))
            if args.look:
                update["look"] = args.look
            if args.accent:
                update["brand"] = {"accent": args.accent}
            for key in ("speaker", "role", "description"):
                if getattr(args, key):
                    update[key] = getattr(args, key)
            if args.handle:
                update["handle"] = {"text": args.handle}
            if args.logo:
                logo = Path(args.logo).resolve()
                if not logo.is_file():
                    raise PresetError(f"logo not found: {logo}")
                update["logo"] = {"src": str(logo)}
            if not update:
                ap.error("save needs something to save: --look, --accent, --from-spec, --from, ...")
            p = save(args.name, update)
            print(json.dumps({"saved": str(p), "preset": load(args.name)}, ensure_ascii=False, indent=1))
    except (PresetError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

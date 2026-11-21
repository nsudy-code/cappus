#!/usr/bin/env python3
"""Show the looks: tested font, color and motion combinations for an edit.

  looks.py                 # every look, with what it is for
  looks.py clean_tech      # one look in full (styles, pairings, cards, transitions, music)
  looks.py suggest --theme "liburan pantai" --scan scan/footage.json --record
                           # the look, font pairing, accent and music for this edit, different
                           # from the user's last edits (history in ~/.cappus/history.json)

In a spec: "look": "clean_tech", optionally "brand": {"accent": "#F59E0B"}. The look's styles
(title, accent, big, label, caption) become available as "style": "title" and so on.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

LOOKS_FILE = Path(__file__).resolve().parent / "looks.json"
COLOR_KEYS = ("text", "accent", "muted", "background")
_cache = None


class LookError(Exception):
    pass


def looks() -> dict:
    global _cache
    if _cache is None:
        _cache = json.loads(LOOKS_FILE.read_text(encoding="utf-8"))["looks"]
    return _cache


def colors(name: str, brand=None) -> dict:
    if name not in looks():
        raise LookError(f"unknown look '{name}'. Looks: {', '.join(sorted(looks()))}")
    out = dict(looks()[name]["colors"])
    if brand is not None:
        if not isinstance(brand, dict):
            raise LookError("spec.brand must be an object like {\"accent\": \"#F59E0B\"}")
        unknown = [k for k in brand if k not in COLOR_KEYS]
        if unknown:
            raise LookError(f"spec.brand: unknown key(s) {unknown}. Allowed: {list(COLOR_KEYS)}")
        for k, v in brand.items():
            if not (isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v)):
                raise LookError(f"spec.brand.{k} must be '#RRGGBB', got {v!r}")
            out[k] = v
    return out


def _fill(value, palette):
    if isinstance(value, str) and value.startswith("$"):
        return palette.get(value[1:], value)
    if isinstance(value, dict):
        return {k: _fill(v, palette) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, palette) for v in value]
    return value


FONTS_FILE = Path(__file__).resolve().parent / "fonts.json"
_fonts = None


def _width(alias):
    global _fonts
    if _fonts is None:
        _fonts = json.loads(FONTS_FILE.read_text(encoding="utf-8")).get("fonts", {})
    return float(_fonts.get(alias, {}).get("width", 2.6))


def check_fonts(fonts):
    if fonts is None:
        return None
    if not isinstance(fonts, dict) or set(fonts) - {"headline", "body"} or not fonts:
        raise LookError('spec.fonts must be {"headline": "<font>", "body": "<font>"} (either or both)')
    _width("anton")
    unknown = [f for f in fonts.values() if f not in _fonts]
    if unknown:
        raise LookError(f"spec.fonts: {unknown} not in fonts.json (the curated fonts); see looks.py <look> for its pairings")
    return fonts


def styles(name: str, brand=None, fonts=None) -> dict:
    """The look's text styles with its colors (or the brand's) filled in. fonts swaps the look's
    headline and/or body font (a pairing), scaling each style's size by the fonts' width so lines keep
    about the same length on screen."""
    palette = colors(name, brand)
    fonts = check_fonts(fonts) or {}
    base = looks()[name]["fonts"]
    out = {}
    for key, st in looks()[name]["styles"].items():
        st = _fill(copy.deepcopy(st), palette)
        for role in ("headline", "body"):
            if role in fonts and st.get("font") == base[role] and fonts[role] != base[role]:
                ratio = max(0.4, min(1.5, _width(base[role]) / _width(fonts[role])))
                st["font"] = fonts[role]
                for size_key in ("size", "size_max"):
                    if size_key in st:
                        st[size_key] = round(st[size_key] * ratio, 1)
                break
        out[key] = st
    return out


# words in the request -> looks that suit it, best first (English and Indonesian)
THEMES = [
    (("dokter", "doctor", "dr.", "kesehatan", "sehat", "health", "medis", "medical", "edukasi", "education",
      "tips", "belajar", "guru", "teacher", "tutorial", "penjelasan", "explainer", "fakta", "nutrisi", "gizi",
      "psikolog", "skincare", "parenting", "finansial", "keuangan"), ("edu", "talk")),
    (("podcast", "kajian", "ceramah", "dakwah", "interview", "wawancara", "ngobrol", "talkshow", "talk show",
      "talking head", "opini", "opinion", "cerita", "storytime", "motivasi", "motivation"), ("talk", "edu")),
    (("wedding", "nikah", "pernikahan", "fashion", "beauty", "kecantikan", "hotel", "villa", "property", "properti",
      "rumah", "jewelry", "perhiasan", "salon", "klinik", "clinic", "luxury", "mewah", "parfum"), ("luxury", "cinematic")),
    (("sport", "olahraga", "gym", "fitness", "motor", "mobil", "car ", "gaming", "game", "streetwear", "skate",
      "basket", "futsal", "bola", "racing"), ("street", "bold_promo")),
    (("anak", "kids", "baby", "bayi", "cafe", "kafe", "kopi", "coffee", "kue", "cake", "dessert", "food", "makanan",
      "kuliner", "pet", "kucing", "anjing", "birthday", "ultah", "ulang tahun", "lucu", "fun"), ("playful", "cinematic")),
    (("website", "web", "app", "aplikasi", "saas", "startup", "software", "jasa", "service", "agency", "agensi",
      "company", "perusahaan", "kursus", "course", "konsultan"), ("kinetic", "clean_tech")),
    (("jualan", "promo", "sale", "diskon", "discount", "produk", "product", "launch", "toko", "shop", "store",
      "offer", "iklan", "ads"), ("bold_promo", "kinetic")),
    (("event", "acara", "party", "pesta", "konser", "concert", "festival", "seminar", "wisuda", "graduation"),
     ("bold_promo", "cinematic")),
    (("travel", "trip", "liburan", "holiday", "vacation", "jalan-jalan", "pantai", "beach", "gunung", "mountain",
      "hiking", "wisata", "bali", "explore", "vlog", "day in the life", "keluarga", "family"), ("cinematic", "street")),
]
HISTORY_KEEP = 20


def history_path() -> Path:
    import os
    cfg = os.environ.get("CAPPUS_CONFIG")
    return (Path(cfg).parent if cfg else Path.home() / ".cappus") / "history.json"


def load_history() -> list:
    try:
        data = json.loads(history_path().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def suggest(theme="", scan=None, site=None, brand_accent=None, seed=None, history=None) -> dict:
    """Pick a look, a font pairing, an accent color and the music for one edit, from the theme words,
    the footage (scan_footage.py's footage.json) or the site (site_capture.py's site.json), and so that
    it differs from the recent edits in history. Returns a ready "spec" part, the other choices and why."""
    import random
    words = f" {theme.lower()} "
    why, candidates = [], []
    for keys, picks in THEMES:
        if any(k in words for k in keys):
            candidates += [p for p in picks if p not in candidates]
    if candidates:
        why.append(f"theme '{theme}' suits {', '.join(candidates[:2])}")
    else:
        candidates = ["cinematic", "bold_promo"] if scan else ["kinetic", "bold_promo"]
        why.append("no theme words matched, so " + ("footage starts from cinematic" if scan else
                                                     "with no footage, kinetic typography"))
    palette = (scan or {}).get("palette") or {}
    pace = palette.get("pace")
    lights = palette.get("light") or {}
    light = max(lights, key=lights.get) if lights else None
    if pace:
        why.append(f"the footage is {pace}-paced, mostly {light} light")
    recent = [(h.get("look"), h.get("headline")) for h in (history or [])][-2:]
    rng = random.Random(seed)
    options = []
    for rank, name in enumerate(candidates[:2]):
        lk = looks()[name]
        default = [{"headline": lk["fonts"]["headline"], "body": lk["fonts"]["body"], "mood": "default",
                    "energy": "any", "light": "any"}]
        pairs = lk.get("pairings") or default
        for idx, pr in enumerate(pairs):
            # earlier pairings are the ones people liked more (the first is the look's favorite)
            score = 3.0 - rank * 1.5 + (len(pairs) - idx) * 0.2
            if pace:
                score += 1.0 if pr["energy"] == pace else 0.3 if pr["energy"] == "any" else -1.0
            if light:
                score += 0.8 if pr["light"] == light else 0.2 if pr["light"] == "any" else -0.6
            if (name, pr["headline"]) in recent:
                score -= 4.0  # never the same as the last two edits
            options.append((score + rng.random() * 0.45, name, pr))
    options.sort(key=lambda o: -o[0])
    _, name, pr = options[0]
    site_accent = ((site or {}).get("colors") or {}).get("accent")
    accent = brand_accent or site_accent or palette.get("accent")
    if accent:
        why.append("accent color from " + ("the brand" if brand_accent else "the site" if site_accent else "the footage"))
    music = dict(looks()[name]["music"])
    if pace == "high":
        music["bpm"] = min(140, music["bpm"] + 6)
    elif pace == "low":
        music["bpm"] = max(80, music["bpm"] - 6)
    spec = {"look": name, "fonts": {"headline": pr["headline"], "body": pr["body"]}}
    if accent:
        spec["brand"] = {"accent": accent}
    why.append(f"{name} with {pr['headline']} + {pr['body']}: {pr['mood']}")
    if recent:
        why.append("the last edits used " + ", ".join(f"{lk_} / {h}" for lk_, h in recent))
    lk = looks()[name]
    return {"spec": spec, "music": music, "transitions": lk["transitions"], "hit": lk["hit"], "filter": lk["filter"],
            "cards": lk["cards"], "why": why,
            "alternatives": [{"look": n, "fonts": {"headline": p["headline"], "body": p["body"]}, "mood": p["mood"]}
                             for _, n, p in options[1:4]]}


def record(choice):
    hist = load_history()
    hist.append({"look": choice["spec"]["look"], "headline": choice["spec"]["fonts"]["headline"],
                 "body": choice["spec"]["fonts"]["body"]})
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(hist[-HISTORY_KEEP:], indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("look", nargs="?", help="a look to show in full, or 'suggest'")
    ap.add_argument("--theme", default="", help="suggest: the user's words about the video")
    ap.add_argument("--scan", help="suggest: footage.json from scan_footage.py")
    ap.add_argument("--site", help="suggest: site.json from site_capture.py")
    ap.add_argument("--accent", help="suggest: the brand's own accent color, #RRGGBB")
    ap.add_argument("--seed", type=int, help="suggest: a fixed choice (tests)")
    ap.add_argument("--record", action="store_true", help="suggest: remember the choice so the next edit differs")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if args.look == "suggest":
        load = lambda f: json.loads(Path(f).read_text(encoding="utf-8")) if f else None
        choice = suggest(args.theme, load(args.scan), load(args.site), args.accent, args.seed, load_history())
        if args.record:
            record(choice)
        print(json.dumps(choice, indent=1, ensure_ascii=False))
        return 0
    if not args.look:
        for name, lk in looks().items():
            print(f"{name:12} {lk['description']}")
            print(f"{'':12} fonts: {lk['fonts']['headline']} + {lk['fonts']['body']}; music: "
                  f"{lk['music']['mood']} {lk['music']['bpm']} BPM")
        return 0
    if args.look not in looks():
        print(f"unknown look '{args.look}'. Looks: {', '.join(sorted(looks()))}", file=sys.stderr)
        return 2
    print(json.dumps(looks()[args.look], indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

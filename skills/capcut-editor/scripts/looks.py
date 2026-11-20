#!/usr/bin/env python3
"""Show the looks: tested font, color and motion combinations for an edit.

  looks.py                 # every look, with what it is for
  looks.py clean_tech      # one look in full (styles, cards, transitions, music)

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
    return value


def styles(name: str, brand=None) -> dict:
    """The look's text styles with its colors (or the brand's) filled in."""
    palette = colors(name, brand)
    return {k: _fill(copy.deepcopy(v), palette) for k, v in looks()[name]["styles"].items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("look", nargs="?")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
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

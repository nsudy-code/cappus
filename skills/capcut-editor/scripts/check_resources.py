#!/usr/bin/env python3
"""Find catalog items that CapCut no longer loads ("animation loss", or a font that falls back).

The catalog comes from pycapcut, and CapCut has withdrawn some of its ids since. Only CapCut itself
can tell: when it opens a draft it downloads every resource and writes the local file path into the
draft. An item it cannot fetch keeps an empty path, and CapCut shows it as missing.

  check_resources.py probe                  # draft "cappus-check": every curated animation and font
  check_resources.py probe --kinds all      # also transitions, filters and effects (bigger download)
  check_resources.py probe --every          # every catalog item of those kinds, not only curated picks
  check_resources.py probe --kinds all --every animations   # whole catalog for animations only
  check_resources.py probe --recheck        # include items already marked broken, to see if they are back
  check_resources.py read                   # after opening cappus-check in CapCut: what failed to load
  check_resources.py read "My draft"        # the same for any draft (e.g. one showing "animation loss")
  check_resources.py read --save            # record failures in unavailable.json, clear items that load again
  check_resources.py read cappus-check-1 cappus-check-2 --save   # a probe split into several drafts

Workflow: probe, then open the draft in CapCut, play it through once and wait until nothing is still
loading, go back to CapCut's home screen, then read --save. Big probes are split into drafts of about
MAX_PER_DRAFT items (CapCut stops downloading when one draft asks for too many); open them one at a time.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import struct
import sys
import zlib
from pathlib import Path

from _common import (KINDS, UNAVAILABLE_FILE, SpecError, alias_for, config_path, draft_folder, find_drafts_dir,
                     is_pro, label, unavailable, unavailable_note)
from build_draft import MARKER, Builder, write_draft

GROUPS = {
    "animations": ["video_intro", "video_outro", "video_combo", "text_intro", "text_outro", "text_loop"],
    "fonts": ["font"],
    "transitions": ["transition"],
    "filters": ["filter"],
    "effects": ["scene_effect", "character_effect"],
}
DEFAULT_GROUPS = ["animations", "fonts"]
PROBE_NAME = "cappus-check"
SLOT = 1.0  # seconds per probed item
MAX_PER_DRAFT = 270  # a 269-item probe loaded fully in CapCut 9.8; 1,497 at once did not

# (animation type, material type) as CapCut stores them -> catalog kind
ANIM_KIND = {
    ("in", "video"): "video_intro", ("out", "video"): "video_outro", ("group", "video"): "video_combo",
    ("in", "sticker"): "text_intro", ("out", "sticker"): "text_outro", ("loop", "sticker"): "text_loop",
}


def kinds_from(values) -> list:
    out = []
    for v in values or DEFAULT_GROUPS:
        for part in str(v).replace(",", " ").split():
            if part == "all":
                names = [k for g in GROUPS.values() for k in g]
            elif part in GROUPS:
                names = GROUPS[part]
            elif part in KINDS and any(part in g for g in GROUPS.values()):
                names = [part]
            else:
                valid = sorted(set(GROUPS) | {k for g in GROUPS.values() for k in g} | {"all"})
                raise SpecError(f"cannot probe '{part}'. Choose from: {', '.join(valid)}")
            out += [k for k in names if k not in out]
    return out


def probe_png() -> Path:
    """A plain 1080x1920 still for the probe's video clips, kept next to the user's config."""
    path = config_path().parent / "probe-frame.png"
    if path.is_file():
        return path
    w, h = 1080, 1920
    row = b"\x00" + bytes((40, 44, 52)) * w
    raw = zlib.compress(row * h, 9)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", raw) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path


def probe_items(kinds, every_kinds, recheck) -> list:
    items = []
    for kind in kinds:
        for member in KINDS[kind][0]:
            if kind not in every_kinds and alias_for(kind, member) is None:
                continue
            if unavailable_note(kind, member) and not recheck:
                continue
            items.append((kind, member))
    return items


def cmd_probe(args) -> int:
    kinds = kinds_from(args.kinds)
    # --every alone: every kind being probed; --every <groups>: only those
    every = set() if args.every is None else (set(kinds_from(args.every)) if args.every else set(kinds))
    items = probe_items(kinds, every, args.recheck)
    if not items:
        print("nothing to probe for those kinds", file=sys.stderr)
        return 1
    if args.drafts_dir:  # always the folder asked for, made if needed; never a default instead
        drafts = Path(args.drafts_dir)
        drafts.mkdir(parents=True, exist_ok=True)
    else:
        drafts = find_drafts_dir()
    if drafts is None:
        print("CapCut's draft folder was not found; pass --drafts-dir", file=sys.stderr)
        return 2
    # CapCut stops fetching new animations when a draft asks for too many at once, so big checks
    # are split into several drafts of about MAX_PER_DRAFT items each.
    parts = args.parts or max(1, -(-len(items) // MAX_PER_DRAFT))
    names = [args.name] if parts == 1 else [f"{args.name}-{i + 1}" for i in range(parts)]
    written = []
    for name, chunk in zip(names, (items[i::parts] for i in range(parts))):
        try:
            written.append(build_probe(name, chunk, kinds, float(args.slot), args.recheck, drafts))
        except SpecError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
    print(json.dumps({
        "status": f"{len(written)} probe draft(s) written",
        "drafts": written,
        "items": len(items),
        "pro_items": sum(1 for _, m in items if is_pro(m)),
        "rechecking_known_broken": sum(1 for k, m in items if unavailable_note(k, m)),
        "next": "Open each draft in CapCut from the home screen (restart CapCut if they do not show), play it "
                "through once, wait until nothing is loading, and go back to the home screen before opening "
                f"the next. Then run: check_resources.py read {' '.join(names)} --save",
    }, ensure_ascii=False, indent=1))
    return 0


def build_probe(name, items, kinds, slot, recheck, drafts) -> dict:
    anim_d, trans_d = round(min(0.4, slot * 0.8), 3), round(min(0.3, slot / 2), 3)
    by = {k: [m for kk, m in items if kk == k] for k in kinds}
    vid = [(k, m) for k in ("video_intro", "video_outro", "video_combo") for m in by.get(k, [])]
    txt = [(k, m) for k in ("text_intro", "text_outro", "text_loop", "font") for m in by.get(k, [])]
    trans, filt = by.get("transition", []), by.get("filter", [])
    fx = by.get("scene_effect", []) + by.get("character_effect", [])
    slots = max(len(vid), len(trans) + 1, len(txt), len(filt), len(fx), 1)

    png = str(probe_png())
    video = [{"src": png, "duration": slot} for _ in range(slots)]
    for i, (kind, m) in enumerate(vid):
        key = {"video_intro": "intro", "video_outro": "outro", "video_combo": "combo"}[kind]
        video[i][key] = {"name": m} if key == "combo" else {"name": m, "duration": anim_d}
    for i, m in enumerate(trans):
        video[i]["transition"] = {"name": m, "duration": trans_d}
    for i, m in enumerate(filt):
        video[i]["filter"] = {"name": m, "intensity": 80}
    texts = []
    for i, (kind, m) in enumerate(txt):
        t = {"text": f"{kind}: {alias_for(kind, m) or m.name}", "at": i * slot, "duration": slot,
             "size": 7, "bold": True}
        if kind == "font":
            t["font"] = m
        else:
            t[{"text_intro": "intro", "text_outro": "outro", "text_loop": "loop"}[kind]] = (
                {"name": m} if kind == "text_loop" else {"name": m, "duration": anim_d})
        texts.append(t)
    effects = [{"name": m, "at": i * slot, "duration": slot} for i, m in enumerate(fx)]
    spec = {"name": name, "width": 1080, "height": 1920, "fps": 30,
            "video": video, "texts": texts, "effects": effects}

    builder = Builder(spec, Path(png).parent, allow_pro=True)  # a check draft is never exported
    builder.allow_unavailable = recheck
    builder.build()
    if builder.errors:
        raise SpecError(f"{len(builder.errors)} problem(s) building {name}: " + "; ".join(builder.errors[:5]))
    marker = {"probe": True, "created": datetime.date.today().isoformat(), "kinds": kinds,
              "items": [{"kind": k, "name": m.name, "alias": alias_for(k, m)} for k, m in items]}
    # A probe draft is rebuilt from the catalog on every run, so it needs no backup.
    write_draft(builder, drafts, name, True, json.dumps(marker, ensure_ascii=False, indent=1),
                force=True, backup=False)
    return {"name": name, "items": {k: len(v) for k, v in by.items() if v},
            "length_seconds": round(builder.main_end / 1e6, 1)}


# ---------------------------------------------------------------- read

def timeline_file(folder: Path):
    """The timeline CapCut saved last. 9.x moves drafts into Timelines/<id>/ on first open."""
    files = [p for n in ("draft_content.json", "draft_info.json")
             for p in [folder / n] + sorted(folder.glob(f"Timelines/*/{n}")) if p.is_file()]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def saved_by_capcut(data: dict) -> bool:
    """True once CapCut has saved the draft after loading it: it then stamps its own version and
    fills resource paths. A copy CapCut makes while opening still carries the builder's stamp."""
    return any(path and path not in ("D:", "D:/") for _, _, _, path, _ in entries(data))


def cached_md5s(drafts: Path) -> set:
    """md5 folder names under CapCut's effect cache (User Data/Cache/effect/<n>/<md5>)."""
    root = drafts.parent.parent / "Cache" / "effect"
    found = set()
    try:
        with os.scandir(root) as top:
            for d in top:
                if d.is_dir():
                    try:
                        found.update(e.name for e in os.scandir(d.path) if e.is_dir())
                    except OSError:
                        pass
    except OSError:
        pass
    return found


def by_resource_id(kinds) -> dict:
    idx = {}
    for kind in kinds:
        for m in KINDS[kind][0]:
            idx.setdefault(m.value.resource_id, (kind, m))
            idx.setdefault(m.value.effect_id, (kind, m))
    return idx


def entries(data: dict):
    """Yield (kind or None, resource id, name, path, material id) for every downloadable resource."""
    mats = data.get("materials", {})
    for group in mats.get("material_animations", []):
        for a in group.get("animations", []):
            yield (ANIM_KIND.get((a.get("type"), a.get("material_type"))), a.get("resource_id"), a.get("name"),
                   a.get("path"), group.get("id"))
    for t in mats.get("transitions", []):
        yield "transition", t.get("resource_id") or t.get("effect_id"), t.get("name"), t.get("path"), t.get("id")
    for e in mats.get("effects", []):
        if e.get("type") == "filter":
            yield "filter", e.get("resource_id") or e.get("effect_id"), e.get("name"), e.get("path"), e.get("id")
    for e in mats.get("video_effects", []):
        yield "video_effect", e.get("resource_id") or e.get("effect_id"), e.get("name"), e.get("path"), e.get("id")
    for t in mats.get("texts", []):
        try:
            styles = json.loads(t.get("content") or "{}").get("styles", [])
        except json.JSONDecodeError:
            continue
        seen = set()
        for s in styles:
            font = s.get("font") or {}
            if font.get("id") and font["id"] not in seen:
                seen.add(font["id"])
                yield "font", font["id"], "", font.get("path"), t.get("id")


def seg_starts(data: dict) -> dict:
    """material id -> start (seconds) of the timeline segment that uses it."""
    out = {}
    for track in data.get("tracks", []):
        for seg in track.get("segments", []):
            t = (seg.get("target_timerange") or {}).get("start", 0) / 1e6
            for ref in [seg.get("material_id")] + list(seg.get("extra_material_refs") or []):
                if ref:
                    out.setdefault(ref, t)
    return out


def fetched_since(path, since: float) -> bool:
    """True if CapCut downloaded this resource after `since` (its cache folder is newer)."""
    try:
        st = os.stat(path)
    except (OSError, TypeError, ValueError):
        return False
    return getattr(st, "st_birthtime", st.st_ctime) >= since


def load_opened(folder: Path):
    """(timeline file, data) for a draft CapCut has opened and saved; raises SpecError otherwise."""
    tfile = timeline_file(folder)
    if tfile is None:
        raise SpecError(f"no draft_content.json / draft_info.json in '{folder.name}'")
    if (folder / ".locked").exists():
        raise SpecError(f"'{folder.name}' is still open in CapCut, which saves the download results only when "
                        "you leave the editor. Go back to CapCut's home screen, then run read again. (If CapCut "
                        "is closed and this persists, CapCut left a stale .locked file in the draft folder.)")
    marker = folder / MARKER
    if marker.is_file() and tfile.stat().st_mtime - marker.stat().st_mtime < 5:
        raise SpecError(f"CapCut has not opened '{folder.name}' since it was built, so nothing is known yet. Open "
                        "it in CapCut, play it through, go back to the home screen, then run read again.")
    try:
        data = json.loads(tfile.read_bytes().decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SpecError(f"{tfile.name} in '{folder.name}' is not plain JSON - cannot read it.")
    if marker.is_file() and not saved_by_capcut(data):
        raise SpecError(f"CapCut opened '{folder.name}' but has not saved what it downloaded (no resource has a "
                        "local path yet). Open it, play it through, wait, go back to the home screen, then read again.")
    return tfile, data


def cmd_read(args) -> int:
    drafts = find_drafts_dir(args.drafts_dir)
    folders, problems = [], []
    for name in args.draft or [PROBE_NAME]:
        folder = draft_folder(name, drafts)
        if folder is None:
            problems.append(f"draft '{name}' not found")
            continue
        try:
            folders.append((folder, *load_opened(folder)))
        except SpecError as e:
            problems.append(str(e))
    if problems:
        for p in problems:
            print(p, file=sys.stderr)
        return 1

    all_kinds = [k for g in GROUPS.values() for k in g]
    index = {k: by_resource_id([k]) for k in all_kinds}
    index["video_effect"] = by_resource_id(["scene_effect", "character_effect"])
    cache = cached_md5s(folders[0][0].parent)
    ok, bad, unsure, other, incomplete, placed = {}, {}, {}, 0, {}, set()
    for folder, _, data in folders:
        marker = folder / MARKER
        built = marker.stat().st_mtime if marker.is_file() else folder.stat().st_ctime
        starts = seg_starts(data)
        seen = {}
        for kind, rid, name, path, mat in entries(data):
            hit = index.get(kind, {}).get(rid) if kind else None
            if hit is None:
                other += 1  # placed by hand in CapCut or not in the catalog: not ours to judge
                continue
            k, m = hit
            has_path = bool(path) and path not in ("D:", "D:/")
            seen[(k, m.name)] = [m, has_path or (m.value.md5 in cache),
                                 starts.get(mat, 0.0), has_path and fetched_since(path, built), has_path]
        # A failure is only an empty path, which is also what a download CapCut never ran looks like. Count
        # failures of a kind as evidence only if CapCut was fetching that kind in this draft: it downloaded
        # new items of it, and (for 10+ items) did not stop before most of the failures.
        for k in {key[0] for key in seen}:
            got = [v for key, v in seen.items() if key[0] == k]
            fails = [v[2] for v in got if not v[1]]
            if not fails:
                continue
            new = [v[2] for v in got if v[3]]
            if not new:
                why = "CapCut downloaded no new item of this kind in this draft"
            elif len(got) >= 10 and sum(1 for t in fails if t > max(new)) > len(fails) / 2:
                why = "most failures come after the last item CapCut downloaded"
            else:
                continue
            incomplete[f"{folder.name}: {k}"] = f"{len(fails)} of {len(got)} failed; {why}"
            for key, v in seen.items():
                if key[0] == k and not v[1]:
                    unsure[key] = v[0]
                    v[1] = None
        for key, (m, loaded, _, _, has_path) in seen.items():
            if loaded:
                ok[key] = m
                if has_path:
                    placed.add(key)
            elif loaded is False:
                bad[key] = m
    for key in ok:  # loaded in any draft counts as loaded
        bad.pop(key, None)
        unsure.pop(key, None)
    for key in bad:
        unsure.pop(key, None)

    app = folders[0][2].get("last_modified_platform") or {}
    capcut = f"CapCut {app.get('app_version', '?')} ({(app.get('os') or '?').capitalize()})"
    # Only an item CapCut actually placed in this draft comes off the list; a cached copy alone may be stale.
    back = [(k, n) for (k, n) in ok if (k, n) in placed and unavailable_note(k, ok[(k, n)])]
    report = {
        "drafts": [f.name for f, _, _ in folders],
        "files": [str(t) for _, t, _ in folders],
        "seen_in": capcut,
        "checked": len(ok) + len(bad) + len(unsure),
        "loaded": len(ok),
        "failed": [f"{k}: {label(k, m)}" + (" PRO" if is_pro(m) else "") for (k, _), m in sorted(bad.items())],
        "working_again": [f"{k}: {label(k, ok[(k, n)])}" for k, n in sorted(back)],
    }
    if unsure:
        report["not_confirmed"] = [f"{k}: {label(k, m)}" + (" PRO" if is_pro(m) else "")
                                   for (k, _), m in sorted(unsure.items())]
        report["not_confirmed_why"] = incomplete
        report["not_confirmed_note"] = (
            "These did not load here, but CapCut may simply not have fetched them, so --save does not record "
            "them. Replace them in this draft anyway; to settle them, probe again in smaller drafts (--parts) "
            "and play each one all the way through.")
    if other:
        report["not_in_catalog"] = other

    savable = bad
    if args.save:
        report["saved"] = save(savable, back, capcut)
    elif back or any(not unavailable_note(k, m) for (k, _), m in savable.items()):
        report["saved"] = "no (add --save to record this in unavailable.json)"
    elif savable:
        report["saved"] = "all failures are already recorded in unavailable.json"
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


def save(bad: dict, back: list, capcut: str) -> str:
    try:
        data = json.loads(UNAVAILABLE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    today = datetime.date.today().isoformat()
    added = 0
    for (kind, name) in bad:
        bucket = data.setdefault(kind, {})
        if name not in bucket:
            added += 1
        bucket[name] = f"did not load in {capcut}, {today}"
    for kind, name in back:
        data.get(kind, {}).pop(name, None)
    ordered = {k: data[k] for k in data if k.startswith("_")}
    for kind in KINDS:
        if data.get(kind):
            ordered[kind] = dict(sorted(data[kind].items()))
    UNAVAILABLE_FILE.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    unavailable(reload=True)
    return f"{UNAVAILABLE_FILE.name}: {added} newly marked broken, {len(back)} cleared (load again)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe", help="build a draft that uses every item to check")
    p.add_argument("--kinds", nargs="*", help=f"groups or kinds (default: {' '.join(DEFAULT_GROUPS)}; "
                                              f"groups: {', '.join(GROUPS)}, all)")
    p.add_argument("--every", nargs="*", metavar="GROUP",
                   help="every catalog item, not only curated (aliased) picks; optionally only for these groups")
    p.add_argument("--slot", type=float, default=SLOT, help=f"seconds per item (default {SLOT})")
    p.add_argument("--parts", type=int, default=0,
                   help=f"split into this many drafts (default: one per ~{MAX_PER_DRAFT} items)")
    p.add_argument("--recheck", action="store_true", help="include items already marked broken")
    p.add_argument("--name", default=PROBE_NAME)
    p.add_argument("--drafts-dir")
    r = sub.add_parser("read", help="report which resources a CapCut-opened draft failed to load")
    r.add_argument("draft", nargs="*", help=f"one or more draft names (default: {PROBE_NAME})")
    r.add_argument("--save", action="store_true", help="update unavailable.json with the result")
    r.add_argument("--drafts-dir")
    args = ap.parse_args()
    try:
        return cmd_probe(args) if args.cmd == "probe" else cmd_read(args)
    except SpecError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

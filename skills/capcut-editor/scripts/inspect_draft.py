#!/usr/bin/env python3
"""Read an existing CapCut draft: its timeline, and the raw resource ids it uses.

  inspect_draft.py --list                    # drafts in CapCut's draft folder
  inspect_draft.py "My draft"                # timeline summary + sticker / fancy-text / bubble ids
  inspect_draft.py "My draft" --diff         # compare with the spec this tool built it from
  inspect_draft.py path/to/draft_folder      # a folder path works too

Use it to (a) see what the user changed in CapCut before rebuilding, and (b) harvest ids of
stickers, fancy-text styles and text bubbles the user placed by hand, for reuse in a spec.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _common import MARKER, edit_check, find_drafts_dir, newest_timeline

# The timeline file CapCut saved last: 8.x re-saves draft_content.json and leaves draft_info.json as
# the tool wrote it, 9.x writes Timelines/<id>/draft_content.json, other builds do the reverse.
load = newest_timeline


def summarize(data: dict) -> dict:
    mats = data.get("materials", {})
    by_id = {}
    for kind, items in mats.items():
        for m in items or []:
            if isinstance(m, dict) and "id" in m:
                by_id[m["id"]] = (kind, m)
    canvas = data.get("canvas_config", {})
    out = {
        "canvas": f"{canvas.get('width')}x{canvas.get('height')}@{data.get('fps')}",
        "duration": round(data.get("duration", 0) / 1e6, 3),
        "app": (data.get("last_modified_platform") or {}).get("app_version"),
        "tracks": [],
    }
    for t in data.get("tracks", []):
        segs = []
        for s in t.get("segments", []):
            tr = s.get("target_timerange") or {}
            kind, m = by_id.get(s.get("material_id"), (None, {}))
            label = m.get("material_name") or m.get("name") or ""
            if kind == "texts":
                try:
                    label = json.loads(m.get("content", "{}")).get("text", "")
                except json.JSONDecodeError:
                    label = str(m.get("content", ""))[:40]
            extras = []
            for ref in s.get("extra_material_refs", []):
                k, em = by_id.get(ref, (None, {}))
                if k and k not in ("speeds", "canvases", "sound_channel_mappings", "vocal_separations",
                                   "placeholder_infos", "material_colors"):
                    extras.append(f"{k}:{em.get('name') or em.get('type') or ''}".rstrip(":"))
                if k == "material_animations":
                    extras[-1] = "anim:" + ",".join(a.get("name", "") for a in em.get("animations", []))
            segs.append(f"{tr.get('start', 0) / 1e6:7.2f} +{tr.get('duration', 0) / 1e6:6.2f}  {label[:40]}"
                        + (f"  [{'; '.join(extras)}]" if extras else ""))
        out["tracks"].append({"type": t.get("type"), "name": t.get("name"), "segments": segs})
    out["stickers"] = [{"resource_id": m.get("resource_id"), "name": m.get("name", "")}
                       for m in mats.get("stickers", [])]
    out["fancy_text"] = [{"effect_id": m.get("resource_id"), "name": m.get("name", "")}
                         for m in mats.get("effects", []) if m.get("type") == "text_effect"]
    out["bubbles"] = [{"effect_id": m.get("effect_id"), "resource_id": m.get("resource_id"),
                       "name": m.get("name", "")}
                      for m in mats.get("effects", []) if m.get("type") == "text_shape"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("draft", nargs="?", help="draft name or folder path")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--diff", action="store_true", help="also show the spec this tool built the draft from")
    ap.add_argument("--drafts-dir")
    args = ap.parse_args()

    drafts = find_drafts_dir(args.drafts_dir)
    if args.list or not args.draft:
        if drafts is None:
            print("CapCut draft folder not found; pass --drafts-dir", file=sys.stderr)
            return 2
        rows = []
        for d in sorted(drafts.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if d.is_dir() and not d.name.startswith("."):
                path, _ = load(d)
                tag = "built-by-tool" if (d / MARKER).exists() else ("" if path else "no timeline file")
                rows.append(f"{d.name}  {tag}".rstrip())
        print("\n".join(rows) or "(no drafts)")
        return 0

    folder = Path(args.draft)
    if not folder.is_dir() and drafts is not None:
        folder = drafts / args.draft
    if not folder.is_dir():
        print(f"draft '{args.draft}' not found", file=sys.stderr)
        return 2
    path, data = load(folder)
    if path is None:
        print("no draft_info.json / draft_content.json in that folder", file=sys.stderr)
        return 1
    if data is None:
        print(f"{path.name} is not plain JSON (encrypted, e.g. a JianYing draft) - cannot read it.", file=sys.stderr)
        return 1
    report = summarize(data)
    report["file"] = str(path)
    spec_file = folder / MARKER
    if spec_file.exists():
        state = edit_check(folder)
        report["edited_in_capcut_since_build"] = state["edited"]
        report["edit_check"] = state["how"]
        if state.get("changes"):
            report["changes_in_capcut"] = state["changes"]
        if args.diff:
            report["built_from_spec"] = json.loads(spec_file.read_text(encoding="utf-8"))
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

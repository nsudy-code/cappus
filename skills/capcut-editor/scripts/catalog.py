#!/usr/bin/env python3
"""Search the catalog of resources that exist inside CapCut (effects, transitions, ...).

  catalog.py kinds
  catalog.py transition                 # curated picks (items with an English alias)
  catalog.py transition glitch flash    # keyword search (alias or CapCut name, any keyword matches)
  catalog.py scene_effect --all         # every item, including un-aliased ones
  catalog.py scene_effect shake --params  # show slider parameters (0-100 each, in this order)

Pro items are included when the user's plan is Pro (tier.py pro). Override with --pro / --free.
Items CapCut no longer loads (unavailable.json) are hidden; --show-broken lists them, marked BROKEN.
"""
from __future__ import annotations

import argparse
import sys

from _common import KINDS, alias_for, default_duration, is_pro, norm, param_names, unavailable_note, user_tier


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", help="catalog kind, or 'kinds' to list them")
    ap.add_argument("query", nargs="*", help="keywords; an item matches if any keyword is a substring")
    ap.add_argument("--all", action="store_true", help="include items without an English alias")
    plan = ap.add_mutually_exclusive_group()
    plan.add_argument("--pro", dest="pro", action="store_const", const=True,
                      help="include CapCut Pro (subscription) items")
    plan.add_argument("--free", dest="pro", action="store_const", const=False, help="free items only")
    ap.add_argument("--params", action="store_true", help="show adjustable parameter names")
    ap.add_argument("--show-broken", action="store_true",
                    help="also list items CapCut no longer loads (cannot be used in a spec)")
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()

    tier, _ = user_tier()
    show_pro = args.pro if args.pro is not None else tier == "pro"
    plan_note = f"user plan: {tier or 'not set'}; Pro items {'shown' if show_pro else 'hidden'}"

    if args.kind == "kinds":
        for kind, (enum, desc) in KINDS.items():
            free = sum(1 for m in enum if not is_pro(m))
            print(f"{kind:17} {free:4} free / {len(enum):4} total   {desc}")
        print(f"\n({plan_note})")
        return 0
    if args.kind not in KINDS:
        print(f"unknown kind '{args.kind}'. Kinds: {', '.join(KINDS)}", file=sys.stderr)
        return 2

    keys = [norm(q) for q in args.query]
    rows = []
    hidden_broken = 0
    for member in KINDS[args.kind][0]:
        if is_pro(member) and not show_pro:
            continue
        broken = unavailable_note(args.kind, member)
        if broken and not args.show_broken:
            hidden_broken += 1
            continue
        alias = alias_for(args.kind, member)
        hay = norm(member.name) + "|" + norm(alias or "")
        if keys:
            if not any(k in hay for k in keys):
                continue
        elif not alias and not args.all:
            continue
        rows.append((member, alias))

    rows.sort(key=lambda r: (r[1] is None, r[1] or r[0].name))
    for member, alias in rows[: args.limit]:
        parts = [f"{alias or '-':22}", f"{member.name:20}", "PRO " if is_pro(member) else "free"]
        if unavailable_note(args.kind, member):
            parts.append("BROKEN (CapCut no longer loads it)")
        dur = default_duration(member)
        if dur is not None:
            parts.append(f"{dur:.2f}s")
        params = param_names(member)
        if args.params and params:
            parts.append("params: " + ", ".join(p.replace("effects_adjust_", "") for p in params))
        elif params:
            parts.append(f"{len(params)} params")
        print("  ".join(parts))
    shown = min(len(rows), args.limit)
    note = "" if (keys or args.all) else "  (curated picks only; add --all or keywords for more)"
    print(f"\n{shown} of {len(rows)} {args.kind} items{note}. Use either column as the name in the spec.")
    broken_note = f"; {hidden_broken} known-broken hidden (--show-broken)" if hidden_broken else ""
    print(f"({plan_note}{broken_note})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

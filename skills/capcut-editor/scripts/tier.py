#!/usr/bin/env python3
"""Show or set whether this user has CapCut Pro. The answer is saved per user and reused.

  tier.py          # show the current setting
  tier.py pro      # user has CapCut Pro: Pro resources are allowed by default
  tier.py free     # free CapCut: only free resources (also the behaviour while unset)

Saved in ~/.cappus/config.json (override the path with CAPPUS_CONFIG). The CAPPUS_TIER
environment variable (pro/free) takes precedence over the saved value.
"""
from __future__ import annotations

import argparse
import json
import sys

from _common import KINDS, config_path, is_pro, load_config, save_config, user_tier


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("set", nargs="?", choices=["pro", "free"], help="save this user's CapCut plan")
    args = ap.parse_args()

    if args.set:
        cfg = load_config()
        cfg["tier"] = args.set
        save_config(cfg)

    tier, source = user_tier()
    total = sum(len(enum) for enum, _ in KINDS.values())
    free = sum(1 for enum, _ in KINDS.values() for m in enum if not is_pro(m))
    out = {"tier": tier, "source": source, "config_file": str(config_path())}
    if tier == "pro":
        out["resources"] = f"all {total} catalog items (free and Pro)"
        out["note"] = ("Pro resources are allowed without setting allow_pro. Whoever exports the video "
                       "needs CapCut Pro; set \"allow_pro\": false in a spec meant for a free account.")
    elif tier == "free":
        out["resources"] = f"{free} free items only"
        out["note"] = "Pro resources are rejected. Run `tier.py pro` if the user upgrades."
    else:
        out["resources"] = f"{free} free items only (until set)"
        out["note"] = ("Unknown. Ask the user once whether they have CapCut Pro, then save the answer "
                       "with `tier.py pro` or `tier.py free`.")
    if args.set and source != str(config_path()):
        out["warning"] = f"saved '{args.set}', but {source} overrides it"
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

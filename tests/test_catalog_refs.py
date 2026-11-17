"""Every resource name the skill hands to Claude must exist in the CapCut catalog."""
import json
import re

import pytest

from conftest import SCRIPTS, SKILL
from _common import KINDS, aliases, display_name, is_pro, norm, unavailable


def catalog_index(kind, with_aliases=False):
    idx = {}
    for member in KINDS[kind][0]:
        idx.setdefault(norm(member.name), member)
        idx.setdefault(norm(display_name(member)), member)
    if with_aliases:
        for alias, target in aliases().get(kind, {}).items():
            if norm(target) in idx:
                idx[norm(alias)] = idx[norm(target)]
    return idx


def alias_tables(filename):
    data = json.loads((SCRIPTS / filename).read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


@pytest.mark.parametrize("filename, pro", [("aliases.json", False), ("aliases_pro.json", True)])
def test_alias_targets_exist_and_match_their_tier(filename, pro):
    # An alias may point at an item listed in unavailable.json: the builder then explains that CapCut
    # no longer loads it, instead of saying the name does not exist.
    problems = []
    for kind, table in alias_tables(filename).items():
        if kind not in KINDS:
            problems.append(f"unknown kind {kind!r}")
            continue
        idx = catalog_index(kind)
        for alias, target in table.items():
            member = idx.get(norm(target))
            if member is None:
                problems.append(f"{kind}.{alias} -> {target!r}: not in the catalog")
            elif is_pro(member) != pro:
                problems.append(f"{kind}.{alias} -> {target!r}: is {'Pro' if is_pro(member) else 'free'}")
    assert not problems, "\n".join(problems)


def test_unavailable_names_exist():
    problems = []
    for kind, names in unavailable().items():
        if kind not in KINDS:
            problems.append(f"unknown kind {kind!r}")
            continue
        members = {m.name for m in KINDS[kind][0]}
        problems += [f"{kind}.{name}" for name in names if name not in members]
    assert not problems, "not in the catalog: " + ", ".join(problems)


# Palette table columns in editing-craft.md and the catalog kinds a name in them may come from.
PALETTE_COLUMNS = (
    ("transition", "video_intro"),
    ("scene_effect", "character_effect"),
    ("filter",),
    ("text_intro", "text_outro", "text_loop"),
)


def palette_rows():
    text = (SKILL / "references" / "editing-craft.md").read_text(encoding="utf-8")
    start = text.index("## Palette by mood")
    end = text.index("\n## ", text.index("## Pro palette") + 3)
    for line in text[start:end].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0] not in ("mood", "---"):
            yield cells[0], cells[1:]


def test_palette_names_resolve_to_loadable_items():
    rows = list(palette_rows())
    assert len(rows) >= 14, "palette tables not found; did the headings change?"
    indexes = {kind: catalog_index(kind, True) for kinds in PALETTE_COLUMNS for kind in kinds}
    problems = []
    for mood, cells in rows:
        for kinds, cell in zip(PALETTE_COLUMNS, cells):
            for name in re.findall(r"`([^`]+)`", cell):
                found = [(k, indexes[k][norm(name)]) for k in kinds if norm(name) in indexes[k]]
                if not found:
                    problems.append(f"{mood}: {name!r} is not a {' / '.join(kinds)} alias or catalog name")
                elif all(m.name in unavailable().get(k, {}) for k, m in found):
                    problems.append(f"{mood}: {name!r} is listed in unavailable.json")
    assert not problems, "\n".join(problems)

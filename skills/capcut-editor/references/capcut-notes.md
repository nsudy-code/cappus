# CapCut notes: limits, follow-ups, troubleshooting

## Where drafts live

| OS | default draft folder |
|---|---|
| Windows | `%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft` |
| macOS | `~/Movies/CapCut/User Data/Projects/com.lveditor.draft` |

If the user changed **CapCut > Settings > Drafts location**, pass `--drafts-dir <that folder>` or set
the `CAPCUT_DRAFTS` environment variable. If no folder is found, `build_draft.py` writes to
`capcut_drafts/` next to the spec and says so; the user copies the draft folder into their drafts
location.

Each draft folder this tool writes contains `draft_content.json` and `draft_info.json` (same timeline;
older and newer CapCut builds read different ones), `draft_meta_info.json`, and `.cappus.json` (a copy
of the spec, which also marks the draft as safe for `--overwrite`).

Media is **linked, not copied**. Moving or renaming the source files makes CapCut show "media
offline"; relinking in CapCut fixes it.

Target app: **CapCut desktop (international)**, Windows or macOS. The Chinese edition (JianYing 6+)
encrypts its drafts and is not supported. The mobile app does not open desktop drafts directly
(the user can upload the project to CapCut cloud space from desktop).

## Revising a draft

1. `inspect_draft.py "<name>"` - shows the timeline and `edited_in_capcut_since_build`.
2. If the user did not edit it in CapCut: change the spec, `build_draft.py spec.json --overwrite`.
3. If they did: rebuilding discards their manual work. Ask first, or build with a new `name`
   (e.g. "... v2") so both versions exist.
4. CapCut must not have that draft open while you overwrite it; ask the user to go back to the
   CapCut home screen first.

## What the generated draft can do

Cuts, trims, order, constant speed, volume, audio fades, multiple video/audio/text layers,
transform (position/scale/rotation/opacity/flip), linear keyframes (position, scale, rotation,
opacity, saturation, contrast, brightness, volume), In/Out/Combo animations for clips and text,
transitions, per-clip and track-level filters, scene and body effects with slider values, masks,
blend modes, chroma key, background blur/color fill, text with font/color/stroke/shadow/background,
text animations, word-level captions, stickers and fancy text by raw id.

## What it cannot do - tell the user the one-click CapCut way

| want | do in CapCut |
|---|---|
| Speed ramp (curve speed) | Select clip > Speed > Curve. Or approximate in the spec: split the shot into consecutive clips with stepped `speed` values (e.g. 1.0 > 0.4 > 1.0). |
| Auto captions from speech | Text > Auto captions (then style them). |
| Remove background / cutout | Select clip > Video > Remove BG. |
| Freeze frame, reverse | Right-click clip > Freeze / Reverse. |
| Auto reframe | Select clip > Auto reframe. |
| Eased keyframes | Click a keyframe > graph/ease presets. (The spec only produces linear keyframes.) |
| Color grading wheels / HSL / curves / LUT | Select clip > Adjust. (The spec can only set saturation/contrast/brightness via keyframes.) |
| Sound effects, CapCut music library | Audio > Sound effects / Music. |
| Stickers from the library | Stickers panel (or harvest ids, see below). |
| Text templates | Text > Text templates. |
| Noise reduction, voice enhance | Select audio > Reduce noise / Enhance voice. |
| Beat markers | Select music > Beat > Auto generate. |
| Export | Export button (top right). Generated drafts cannot be exported automatically. |

## Stickers, fancy text, bubbles

These have no catalog. To reuse one: ask the user to add it once to any draft by hand, then run
`inspect_draft.py "<that draft>"` and copy the ids into the spec:

```json
"stickers": [{"resource_id": "7226264888031694091", "at": 1, "duration": 2,
              "transform": {"scale": 0.4, "x": 0.5, "y": 0.6}}],
"texts": [{"text": "WOW", "at": 1, "duration": 1, "effect_id": "7296357486490144036"}]
```

## Pro resources

Items marked PRO in the catalog need a CapCut Pro subscription to export. The draft still opens and
previews, which hides the problem until export.

The user's plan is saved per user by `tier.py` (`~/.cappus/config.json`; the `CAPPUS_TIER` env var
overrides it). The builder decides whether Pro items are allowed in this order:

1. `--allow-pro` / `--free-only` on the command line;
2. `"allow_pro"` in the spec;
3. the saved plan (`pro` allows them; `free` or unset does not).

The build report shows the decision in `pro_allowed` and lists every Pro item used in
`pro_resources`. Mention those items at handover, so the user knows what to swap if a free account
ever has to export the draft. To make a free-account copy of a Pro edit, rebuild the same spec with
`--free-only` under a new `name`, and replace each rejected item with one of the suggested free
alternatives.

## Items CapCut no longer loads ("animation loss")

The catalog comes from pycapcut, and CapCut has since withdrawn some of its ids. Such an item looks
fine in the spec and the build, but CapCut cannot download it: an animation shows an "animation
loss" label on the clip, and a font falls back to the default. Items found this way are listed in
`scripts/unavailable.json`. The builder rejects them with alternatives, and `catalog.py` hides them
(`--show-broken` lists them).

To find more, use `check_resources.py`:

- `check_resources.py read "<draft>"` reads a draft that CapCut has opened and lists every catalog
  item that failed to load. Use it when the user reports "animation loss" or a wrong font, then swap
  the failed items in the spec and rebuild.
- `check_resources.py probe` builds a `cappus-check` draft containing every curated animation and
  font (`--kinds all` adds transitions, filters and effects; `--every` uses the whole catalog, not
  only curated picks). The user opens it in CapCut, plays it through once and returns to the home
  screen. `check_resources.py read --save` then records the failures in `unavailable.json` and
  clears items that load again.
- CapCut writes what it downloaded only when the user leaves the editor, so `read` refuses a draft
  that is still open. CapCut also stops downloading when one draft asks for too many items: a
  1,500-item draft left most animations unloaded, while ~270 loaded fully. `probe` therefore splits
  big checks into several drafts (`cappus-check-1`, `-2`, ...). The user opens them one at a time,
  plays each through and returns to the home screen between them; then pass all their names to
  `read`. `read` saves a failure only when CapCut was downloading that kind in that draft (new
  items of it arrived, and not only before most of the failures). Other failures are listed as
  `not_confirmed`: replace them in the draft, but they are not recorded.

State as of CapCut 9.8.0 (Windows): 377 of the catalog's 941 animations no longer load (57 of 256
free, 320 of 685 Pro), mostly older intros and outros. Every curated alias outside the blocklist
loads, and so do all curated transitions, filters, effects and fonts. Prefer curated aliases;
an uncurated animation is fine as long as the builder accepts it.

`unavailable.json` is part of the skill, so commit it to share the result with the team.

## Troubleshooting

| symptom | cause and fix |
|---|---|
| Draft not in the project list | CapCut was open during the build: go back to home or restart it. Custom drafts location: rebuild with `--drafts-dir`. |
| Draft opens but the timeline is empty | Very new CapCut builds may read `Timelines/<id>/draft_info.json`. Report the CapCut version (Settings > About) - this needs a builder update; nothing in the spec will fix it. |
| An effect/transition shows a download spinner | CapCut downloads resources on first use; needs internet. Wait, then it plays. |
| "animation loss", a missing icon, or a font that falls back to the default | CapCut no longer serves that catalog item. Run `check_resources.py read "<draft>"`, replace what it lists, rebuild, and record it with `--save` (see above). |
| "Media offline" | Source files moved or renamed. Relink in CapCut, or fix `src` and rebuild. |
| Text too big/small | Font size is a first guess - adjust `size` in the style and rebuild, or resize in CapCut. |
| Vertical phone video shows sideways | The builder corrects for rotation flags; if it still happens, set `transform.rotation` 90/-90 on that clip. |
| `SegmentOverlap` or similar library error | Report it with the spec; the builder should normally move overlapping items to a new lane. |

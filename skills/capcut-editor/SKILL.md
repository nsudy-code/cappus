---
name: capcut-editor
description: Edit videos by producing a real CapCut draft project that the user opens and keeps editing in CapCut desktop - every cut, text, transition, effect, filter, animation and keyframe stays editable on the timeline. Use this whenever the user wants a video edited, cut, assembled, captioned (including auto captions transcribed from the speech), synced to music, reformatted for TikTok/Reels/Shorts, or made to "look cool" from their footage/photos/audio, and especially when they mention CapCut, a CapCut project/draft/template, or wanting to tweak the result themselves afterwards. Also use it to revise a draft this skill made earlier. Prefer this over rendering a flat MP4 with ffmpeg when the user has (or will install) CapCut desktop on Windows or macOS, unless they explicitly ask for a rendered file only.
---

# CapCut Editor

You edit video the way a human editor does in CapCut, except you write the project file instead of
dragging clips. The output is a **draft** in CapCut's own project format: the user opens it in CapCut
desktop, sees a normal timeline, and can change anything. Nothing is baked in.

Two things make this work, and both are easy to get wrong without the bundled tools:

1. **Only real CapCut resources.** Every transition, effect, filter, animation and font is referenced
   by an internal CapCut ID. A made-up name ("Cinematic Glow") silently does nothing. The bundled
   catalog holds ~5,000 real resources (~1,200 free, ~3,800 Pro); `build_draft.py` refuses anything
   that is not in it, and anything CapCut is known to no longer load (`<skill>/scripts/unavailable.json`).
2. **You cannot watch the result.** You never see the render, so taste has to come from looking at the
   footage first, planning deliberately, and following the craft guidance rather than piling on effects.

## Setup (once per machine)

`<skill>` below means this skill's folder (the one holding this SKILL.md). Commands use `python`; on
macOS and most Linux systems that is usually `python3` (and `python3 -m pip`).

```bash
python <skill>/scripts/doctor.py                     # what is ready and what to fix; needs nothing installed
python -m pip install -r <skill>/requirements.txt    # pycapcut + numpy
```

Run `doctor.py` first on a new machine, and again when a script fails for a reason that is not the
spec. It prints `ready`, `problems` (each with its fix) and `notes`. **If it finds no CapCut
desktop**, say so before planning anything: the draft opens only in CapCut desktop (a free download
for Windows and macOS). Offer the choice: install CapCut and get an editable draft, or get a
finished MP4 rendered with ffmpeg instead.

Captions from speech need one more, optional package (see step 2):
`python -m pip install -r <skill>/requirements-captions.txt` (faster-whisper).

`ffmpeg`/`ffprobe` must be on PATH. If `pip` targets a managed Python, create a venv and run the
scripts with that interpreter. The scripts live in `<skill>/scripts/`. They print JSON, except the
plain-text lists from `catalog.py` and `inspect_draft.py --list`.

## Workflow

### 1. Get the brief - but do not interrogate

You need: the media files, where the video is going (decides aspect ratio), rough length, and the vibe.
Infer what you can and state your assumptions instead of asking a list of questions. Defaults:
vertical 1080x1920 at 30 fps, 15-40 s for short-form.

**Know the user's CapCut plan.** Run `python <skill>/scripts/tier.py` at the start. It prints the saved plan:

- `pro`: the full catalog is open, and Pro items are allowed with no `allow_pro` in the spec. Pro
  often has the more polished option for a job (film-stock looks, real camera moves, light leaks,
  finer text animations - see the Pro palette in `references/editing-craft.md`). Choose the best
  item for each shot whether it is free or Pro. The restraint rules stay the same.
- `free`: only free items. The builder rejects Pro items and suggests free ones.
- `null` (never asked): ask once, in the same message as any other assumptions: "Do you have
  CapCut Pro?" Save the answer with `tier.py pro` or `tier.py free`; it is remembered for later
  sessions. Until then, stay free-only. Do not ask again once it is saved.

Pro matters at export: the account that exports needs Pro, or the export is blocked behind a
paywall even though the draft opens and previews fine. If a Pro user says the draft is for someone
on free CapCut, set `"allow_pro": false` in that spec. Whenever the user states their plan, asked
or not ("I'm on free CapCut", "I have Pro", "switch me to Pro"), save it right away with
`tier.py free` or `tier.py pro` and confirm in one line.

### 2. Look at the footage before deciding anything

```bash
python <skill>/scripts/probe.py clip1.mp4 clip2.mp4 song.mp3              # sizes, durations, fps
python <skill>/scripts/probe.py clip1.mp4 --sheet <scratch_dir> --frames 12   # then Read the JPG it reports
python <skill>/scripts/probe.py clip1.mp4 --sheet <scratch_dir> --from 12 --to 18   # zoom into a moment
python <skill>/scripts/probe.py clip1.mp4 --scenes        # shot changes inside a long file
python <skill>/scripts/probe.py talk.mp4 --silence        # speech segments, for cutting dead air
python <skill>/scripts/probe.py song.mp3 --beats          # bpm, beat times, downbeats, energy curve
python <skill>/scripts/transcribe.py talk.mp4             # what is said, with a time for every word
```

Actually open the contact sheets with the Read tool. Choosing in/out points from filenames and
durations alone produces edits that cut mid-gesture or hold on nothing. Zoom the sheet into a window
whenever you need to place a cut precisely - sheet times are approximate (within one frame-step).

**Speech.** When the footage has someone talking, transcribe it before you plan: the transcript tells
you what is said and when, so you can cut on sentence boundaries, drop flubbed takes and repeats,
open on the strongest line, and caption it. `transcribe.py` runs offline (faster-whisper) and writes
a transcript beside the media (`talk.mp4` -> `talk.transcript.json`; the path is in its output), with
every word's time in the source file. Running it again on the same file reuses that transcript. Read
the `text` it prints; check names and anything under `low_confidence` or marked `(?)` with the user.

- Not installed yet (exit code 3): ask once before installing, because it downloads about 0.6 GB in all:
  ~0.1 GB of packages now, then the default `small` model (~0.5 GB) on the first run. Then run
  `python -m pip install -r <skill>/requirements-captions.txt`.
- Pass `--language id` (or `en`, ...) when you know it, and `--prompt "Name, Brand"` for spellings.
  `--model large-v3-turbo` (~1.6 GB) is more accurate and slower; offer it if `small` gets words wrong.
- With `small` on a laptop CPU it took about a third of the audio's length in testing. Run long files
  in the background.
- If the user declines the install, use their SRT/transcript if they have one, or suggest CapCut's
  **Auto captions** on the finished draft. Never invent timings.

Captions come from the transcript with `"captions": {"transcript": "talk.transcript.json", ...}`.
The builder maps each word through the clips that play that file, so captions stay in sync after
jump cuts, reordering and speed changes, and words in the parts you cut are left out
(`references/edit-spec.md`).

### 3. Plan the edit, briefly, then write the spec

Read `references/editing-craft.md` before planning - it has the pacing rules, the per-genre recipes and
the "which effect for which mood" palette. Sketch a beat sheet (hook, body, payoff, with timestamps),
then express it as an edit spec: one JSON file, times in seconds. Save it next to the user's media (or
in the project folder), because relative `src` paths resolve from the spec's location and the spec is
what you edit when the user asks for changes.

Minimal shape (full reference: `references/edit-spec.md`):

```json
{
  "name": "Bali trip reel",
  "width": 1080, "height": 1920, "fps": 30,
  "styles": {"title": {"size": 14, "bold": true, "stroke": {"color": "#000000", "width": 45},
                       "intro": "zoom_in", "outro": "fade_out"}},
  "video": [
    {"id": "hook", "src": "surf.mp4", "in": 3.2, "out": 5.0, "fit": "cover", "motion": "push_in",
     "transition": {"name": "white_flash", "duration": 0.3}},
    {"id": "walk", "src": "beach.mp4", "in": 10.0, "out": 12.4, "fit": "cover", "speed": 0.5,
     "filter": {"name": "teal_orange", "intensity": 60}}
  ],
  "audio": [{"src": "song.mp3", "in": 31.5, "at": 0, "end": "end", "volume": 0.6,
             "fade": {"in": 0.2, "out": 1.0}}],
  "texts": [{"text": "BALI IN 20 SECONDS", "at": 0.2, "end": "@hook.end", "style": "title", "y": 0.5}],
  "effects": [{"name": "shake", "at": "@walk", "duration": 0.4}]
}
```

How the pieces behave:

- `video` is the main track. Clips play back to back in list order; you never give them a start time.
  `in`/`out` are positions in the source file. Timeline length = `(out - in) / speed`.
- Everything else (`overlays`, `audio`, `texts`, `captions`, `effects`, `filters`) is placed with `at`
  plus `duration` or `end`. Times can be seconds, or references to clip ids: `"@hook"`,
  `"@hook.end-0.3"`, `"@walk+1"`, and `"end"` for the end of the main track. Prefer references - they
  keep text and effects glued to their clip when you retime the cut later.
- Overlapping items on the same track are moved to an extra lane automatically.
- Names come from the catalog. Use the English alias or the original CapCut name - both work.

### 4. Pick resources from the catalog, never from memory

```bash
python <skill>/scripts/catalog.py kinds                       # the 15 kinds and how many are free
python <skill>/scripts/catalog.py transition                  # curated picks with English aliases
python <skill>/scripts/catalog.py scene_effect glitch flash   # keyword search
python <skill>/scripts/catalog.py scene_effect shake --params # slider names; params are 0-100 in that order
python <skill>/scripts/catalog.py filter --all                # every filter, incl. un-aliased ones
```

The catalog follows the user's plan: with `pro` it lists free and Pro items (marked `PRO`), and with
`free` or unset it lists free items only. `--free` / `--pro` override that for one search.

Most original names are Chinese because that is what CapCut ships internally; CapCut shows the
localized name in its UI. You can read them - `--all` lists hundreds more options than the aliased
picks, and a Chinese name is a perfectly valid value in the spec.

### 5. Validate, then build

```bash
python <skill>/scripts/build_draft.py edit.json --check   # all problems at once, with "did you mean" hints
python <skill>/scripts/build_draft.py edit.json           # writes the draft into CapCut's draft folder
```

`--check` prints the resolved timeline. Read it: confirm the total duration, that text sits where you
meant, that nothing runs past the main track, and that `pro_allowed` matches the user's plan. Fix every reported problem and re-check; do not
remove a feature just to make an error go away without understanding it.

To revise after feedback, edit the spec and rebuild with `--overwrite`. It only replaces a draft this
tool created, and only while the user has not changed it in CapCut: each build stores a fingerprint of
the timeline (`.cappus-build.json`), and `--overwrite` refuses once the timeline no longer matches.
Opening and playing the draft does not count as a change. The refusal lists what changed; so does
`python <skill>/scripts/inspect_draft.py "<draft name>"` (`edited_in_capcut_since_build`,
`changes_in_capcut`). Then ask the user: build under a new `name` to keep both versions, or rebuild
with `--force`. `--force` never deletes: the current version moves to `~/.cappus/backups/<name>-<time>`
(the newest 5 per draft are kept), and the build report names the folder under `previous_version`.
Drafts built by cappus 0.4 or older have no fingerprint, so for those, opening the draft in CapCut
already counts as a change.

The draft must not be open in CapCut while you write it. `inspect_draft.py` also reads any draft the
user made by hand, which is how you pick up sticker / fancy-text ids or learn their editing style.

### 6. Hand over honestly

Tell the user:

- the draft name, and that it is in CapCut's project list (if CapCut is already open: go back to the
  home screen or restart it so it rescans);
- a short description of the edit and the reasoning (structure, where the cuts land, what the look is);
- that you have not watched the render, plus the two or three things most worth eyeballing (text
  size/position, a specific transition, music level against speech);
- anything you could not do in the draft and how to do it in CapCut in one click
  (see `references/capcut-notes.md`);
- if the build report lists `pro_resources`: that the draft uses Pro items (name them) and the
  exporting account needs CapCut Pro;
- if any clip uses `remove_bg`: that CapCut cuts those clips out the first time it opens the draft.
  This takes a few seconds per clip (the clip shows "Applying Auto cutout"), and the background
  stays visible until it finishes.

If the user then reports "animation loss", a missing effect or a wrong font, run
`python <skill>/scripts/check_resources.py read "<draft name>"` (after they have opened the draft in CapCut
and gone back to the home screen). It lists the catalog items CapCut could not load, under `failed`
and `not_confirmed`. Replace both in the spec and rebuild. `--save` records the `failed` ones so the
builder rejects them from now on (`references/capcut-notes.md`).

Source media is linked, not copied - warn them not to move or delete the files.

## What makes the edit good (the short version)

The full guidance is in `references/editing-craft.md`. The rules that matter most:

- **Cut for a reason.** Each clip earns its place and leaves early. First clip is the strongest visual,
  not the chronologically first one. On short-form the first 1-2 s decide everything.
- **Music drives pacing.** With music, land cuts on beats and the biggest moment on a downbeat or energy
  jump from `--beats`. Start the song at its good part (`in`), not at 0.
- **Restraint reads as professional.** One font, two colors, one or two transition families, a single
  look (filter) across the piece. Hard cuts for most joins; a transition is punctuation for a change of
  scene, time or energy. Stacking effects on every clip is the most common way to make an edit look cheap.
- **Motion on stills and static shots.** A slow `push_in` or pan gives life; alternate directions.
- **Reframe properly.** Horizontal footage in a vertical canvas: `"fit": "cover"` (crops the sides -
  check the subject stays in frame, shift with `transform.x`) or `"fit": "contain"` with
  `"background": "blur"`. Never leave accidental black bars.
- **Text must be readable in half a second.** Short lines, heavy weight, stroke or shadow for contrast,
  on screen long enough to read twice, inside the platform safe zone.
- **Sound is half the edit.** Fade music in and out, duck it under speech, mute clip audio that is just
  wind and handling noise.

## Reference files

- `references/edit-spec.md` - every field of the spec, units, coordinate system, examples. Read it when
  writing anything beyond the minimal shape above.
- `references/editing-craft.md` - pacing, genre recipes (talking head, beat-synced montage, cinematic
  vlog, product promo, photo slideshow), and the effect/transition/filter palette by mood, with a
  separate Pro palette for CapCut Pro users.
- `references/capcut-notes.md` - what is and is not possible in a generated draft, CapCut-side
  follow-ups, and troubleshooting when a draft does not show up or a resource is missing.

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
2. **You cannot watch the result** (unless you can use the user's screen, see step 6). Taste has to
   come from looking at the footage first, planning deliberately, and following the craft guidance
   rather than piling on effects.

**The first result is what people judge.** Most requests are one line ("make a promo for my
website", "turn these photos into a reel"). With no footage, the default is **kinetic typography** (look `kinetic`,
recipe in `references/recipes.md`): huge words on every beat beat a slideshow of screenshots. Do not answer with questions: follow a recipe in
`references/recipes.md`, start from a tested look (`scripts/looks.py`), generate music on a known
beat grid when there is none (`scripts/music.py`), and use the eased motion presets. State the
choices you made in one line.

## Setup (once per machine)

`<skill>` below means this skill's folder (the one holding this SKILL.md). Commands use `python`; on
macOS and most Linux systems that is usually `python3` (and `python3 -m pip`).

`doctor.py` (step 1 of the workflow) tells you whether any of this is missing.

```bash
python -m pip install -r <skill>/requirements.txt    # pycapcut + numpy + Pillow
```

Captions from speech need one more, optional package (see step 2):
`python -m pip install -r <skill>/requirements-captions.txt` (faster-whisper).

Capturing a website (the website-to-promo recipe) needs Playwright:
`python -m pip install -r <skill>/requirements-web.txt`, then `python -m playwright install chromium`
(about 150 MB). Ask once before installing it.

`ffmpeg`/`ffprobe` must be on PATH. If `pip` targets a managed Python, create a venv and run the
scripts with that interpreter. The scripts live in `<skill>/scripts/`. They print JSON, except the
plain-text lists from `catalog.py` and `inspect_draft.py --list`.

## Workflow

### 1. Check the setup, then get the brief - but do not interrogate

**Run `python <skill>/scripts/doctor.py` at the start of every session**, before anything else, even
if the packages look installed. It takes under a second, needs nothing installed, and reports the
setup and the user's CapCut plan in one call. Run it again when a script fails for a reason that is
not the spec.

- `ready: false`: fix each item in `problems` first. Each says how (usually the pip line in Setup).
- **No CapCut desktop** (a problem says so): tell the user before planning anything. The draft opens
  only in CapCut desktop, a free download for Windows and macOS. Offer the choice: install CapCut
  and get an editable draft, or get a finished MP4 rendered with ffmpeg instead.
- `notes` are not blocking (an untested CapCut version, no speech-to-text package yet). Mention one
  only when it affects this job.

You need: the media files, where the video is going (decides aspect ratio), rough length, and the vibe.
Infer what you can and state your assumptions instead of asking a list of questions. Defaults:
vertical 1080x1920 at 30 fps, 15-40 s for short-form.

**Know the user's CapCut plan.** `plan.tier` in the doctor report is the saved plan:

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
python <skill>/scripts/probe.py talk.mp4 --loudness       # LUFS and peak (the spec's "loudness" levels them)
python <skill>/scripts/transcribe.py talk.mp4             # what is said, with a time for every word
python <skill>/scripts/cut_talk.py talk.mp4               # talking head -> jump-cut spec, hooks, B-roll slots
python <skill>/scripts/faces.py talk.mp4                  # where the face is: crop, punch-in, text spots
python <skill>/scripts/presets.py                         # saved series presets (look, colors, handle, logo)
python <skill>/scripts/shorts.py long.mp4 --count 3       # the best 20-60 s clips of a long talk, one spec each
```

**Many clips?** Sort them first: `python <skill>/scripts/scan_footage.py <folder> --out <scratch_dir>/scan`
splits them into shots, scores each (sharp, exposure, shake, motion), drops duplicates, and gives
each shot its best window, a color correction (`adjust`) and a vertical crop offset (`reframe_x`,
or a `reframe_path` for `transform.x_path` when the subject moves across the frame).
Read its `best.jpg`, then follow "A pile of footage into one edit" in `references/recipes.md`.

Actually open the contact sheet images and look at them. Choosing in/out points from filenames and
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

**Someone talking to camera** (talking head, explainer, podcast clip, doctor or teacher tips): after
`transcribe.py`, run `cut_talk.py talk.mp4` instead of placing the cuts by hand. It writes
`talk.cut.json`, a spec with the pauses, fillers ("um", "eh") and flubbed takes cut out (the last take
of a restarted line is kept), punch-ins alternating with the cuts, an eased zoom in onto a key word
(a number, a rare word, a strong line's first word) that eases back out a beat later, a slow drift on
the other clips, and captions (`--zoom smooth` drops the hard punch-ins, `--zoom cut` keeps only
them; the report's `camera.zooms` says which words got one). With OpenCV
installed (`requirements-faces.txt`; `doctor.py` says) it finds the face: a wide shot is cropped to
vertical around it (following the speaker who moves), punch-ins keep it in place, and captions move
off it; without OpenCV, pass `--face-y` (the face's height from the top) after looking at a frame.
Pass a look: `--look edu` for an expert explaining (doctor, teacher, tips: bigger captions, one
keyword per sentence in the accent color, red-on-white hook title) or `--look talk` for podcasts,
interviews and kajian (capital captions, the word being said lights up); `looks.py suggest` picks
between them from the user's words. `--speaker "dr. Aisya" --role "Dokter Umum"` adds a lower
third. It prints what it cut
and why, the lines ranked as hooks, and B-roll slots with what is said in each. Read the `removed`
list, above all every `retake`, then edit the spec as usual: `--hook-first` opens on the best hook as a
teaser, `--broll a.mp4 b.mp4` fills the slots, or put the user's footage into the slots by hand where
the words name something it shows. Follow "Talking head" in `references/editing-craft.md`.

### 3. Plan the edit, briefly, then write the spec

Read `references/recipes.md` when the request matches one (a website promo, photos or clips to a
reel), and `references/editing-craft.md` for everything else - it has the pacing rules, the
per-genre recipes and the "which effect for which mood" palette.

**Let the footage and the theme choose the look, and never the same one twice in a row.** Run
`python <skill>/scripts/looks.py suggest --theme "<the user's words>" [--scan scan/footage.json]
[--site site/site.json] [--accent "#RRGGBB"] --record` once per new edit. It reads the theme (both
English and Indonesian words), the footage's pace, light and own accent color, and the user's last
edits, and returns the `look`, a tested font pairing (`fonts`), the `brand` accent, the music mood
and BPM, and why. Put its `spec` part into the spec as it is, and say the choice in one line. Use
one of its `alternatives` when the user asks for something different.

**Looks.** `python <skill>/scripts/looks.py` lists the tested looks (font pairing,
colors, text styles with motion, card motion, transitions, music mood and BPM); `looks.py <name>`
shows one. Put `"look": "<name>"` and `"brand": {"accent": "#RRGGBB"}` in the spec and use the
styles `title`, `accent`, `big`, `label` (captions get `caption`). Other fonts: `scripts/fonts.json`
has 50 free fonts picked by eye, with roles and moods.

**Series presets.** When the user makes the same kind of video again and again (a doctor's weekly
tips, a kajian series, one brand), keep its look in a preset so every episode matches:
`presets.py save dr-aisya --look edu --accent "#14B8A6" --speaker "dr. Aisya" --role "Dokter Umum"
--handle "@dr.aisya" --logo logo.png`, or `--from-spec ep1.cut.json` after an edit the user liked.
Then `"preset": "dr-aisya"` in a spec, or `cut_talk.py talk.mp4 --preset dr-aisya`, brings the
look, colors, caption settings, cut settings, lower third, handle and logo; anything set in the
spec or on the command line still wins. Run `presets.py` first when the user names a series or a
person you may have a preset for, and offer to save one after a talking-head edit they liked.

**One long recording, several shorts.** For a podcast, kajian, class or live replay, transcribe it
once, then `shorts.py long.mp4 --count 3` ranks every run of whole sentences 20-60 s long (opens on
a claim, number, question or "you"; never on "jadi"/"and so"; no long break inside; ends on a
finished sentence) and cuts the best ones that don't overlap into `long.short1.cut.json`, ... through
`cut_talk.py --from --to`. Other flags (`--look`, `--preset`, `--denoise`, `--speaker`) go to every
short. Show the user each short's `opening` line and `why` before building; `--list` ranks
without writing. The edits come out shorter than `seconds` (pauses and retakes are cut).

**No music from the user?** Generate it: `python <skill>/scripts/music.py media/music.wav --mood
hype --bpm 124 --length 30 --drop 4 --breath 16 --end-hit 24` writes the track and
`music.beats.json` with every beat time. Build cuts and text changes from that file.

**Sound effects.** `"sfx": "whoosh"` on a transition, `"sfx": "pop"` on a text, or a top-level
`"sfx"` list (`whoosh`, `pop`, `tick`, `hit`, `riser`) adds generated, royalty-free sounds whose peak
lands one frame after the picture, a few dB over the music. A few, where the picture moves or lands.

Sketch a beat sheet (hook, body, payoff, with timestamps),
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
  "texts": [{"text": "BALI, DAY ONE", "at": 0.2, "end": "@hook.end", "style": "title", "y": 0.5}],
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
- `"enter"` / `"exit"` on overlays and texts (`pop`, `punch`, `rise`, `drop`, `slide_left`,
  `grow_left`, `fade`, ...) give eased motion that lands exactly on the item's resting place. Prefer
  them to hand-written keyframes; they combine with a slow drift on the same property.
- Hand-written keyframes can be eased too: `[t, value, "ease_out"]` shapes the segment ending at that
  point, and `"ease": "ease_in_out"` beside the properties sets the default. They land in CapCut as its
  own ease presets, so the user can change them on the keyframe. Linear moves look mechanical: ease
  camera moves (`ease_in_out`) and hits (`cubic_out`, `back_out` for a small overshoot).

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
meant, that nothing runs past the main track, and that `pro_allowed` matches the user's plan. Fix every
reported problem and re-check; do not remove a feature just to make an error go away without
understanding it. Treat a text-fit warning (a line that would wrap or run off the canvas) as a bug:
shorten the line or split it.

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

### 6. Look at it if you can, then hand over

**If computer use is available**, look at the draft in CapCut yourself before handing over: the
first frame, the text changes and the end card (`references/capcut-notes.md`, "Looking at a draft in
CapCut"). Fix what you see and rebuild. Say that you checked it this way.

**If computer use is not available** (or the user declined it), render the preview, Read the
contact sheet, fix, rebuild:

```bash
python <skill>/scripts/preview.py edit.json --out <scratch_dir>/preview   # preview.mp4 + sheet.jpg
```

Read `sheet.jpg` (each tile is labelled with its time and main clip) and check what the preview
can show: each shot frames the subject (cover crop, `transform.x` reframing, push_in/pan), cuts land
where planned, texts and captions appear at the right times, sit inside the safe zone and do not
collide, nothing runs past the end. Add `--every 0.5` to look closer. Fix the spec, rebuild the draft
and render again until the sheet looks right. The preview is an approximation: effects, filters,
transitions, animations and masks are not drawn (the report lists them under `not_drawn`), so never
judge the look from it. Texts use the real font files from CapCut's cache; `fonts` in the report says
which ones stood in because CapCut has not downloaded them yet. In the handover, say you checked a preview render, not
the draft in CapCut. If you did neither, say you have not watched the render.

Write the handover for someone who is not an editor: what to open and press, then what they can
change in one click. Tell the user:

- the draft name, and that it is in CapCut's project list (if CapCut is already open: go back to the
  home screen or restart it so it rescans);
- a short description of the edit and the reasoning (structure, where the cuts land, what the look is);
- whether you looked at it in CapCut (or only at a preview render); if not in CapCut, the two or three things most worth eyeballing (text
  size/position, a specific transition, music level against speech);
- when the music was generated by `music.py`: that it is free to use, and that a CapCut library
  track at the same BPM keeps the sync;
- when the spec has `sfx`: that the sound effects were generated (free to use), that you could not
  listen to them, and that each sits on the `sfx` track to swap, move or delete;
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
  check the subject stays in frame, shift with `transform.x`, or follow a moving one with
  `transform.x_path`) or `"fit": "contain"` with
  `"background": "blur"`. Never leave accidental black bars.
- **Text must be readable in half a second.** Short lines, heavy weight, stroke or shadow for contrast,
  on screen long enough to read twice, inside the platform safe zone.
- **Sound is half the edit.** Fade music in and out, duck it under speech, mute clip audio that is just
  wind and handling noise. Put `"loudness": true` in any spec with speech or music so every file starts
  at -14 LUFS (`cut_talk.py` does); if the report says a peak held a file back, tell the user to select
  it in CapCut > Audio > Normalize loudness. A noisy recording (hum, fan, street) gets `"denoise": true`
  on its clips, or `cut_talk.py --denoise` (CapCut Pro); on a free plan, tell the user to switch on
  Audio > Isolate voice on the clip.

## Reference files

- `references/edit-spec.md` - every field of the spec, units, coordinate system, examples. Read it when
  writing anything beyond the minimal shape above.
- `references/recipes.md` - one-line requests to a finished edit: website to promo video (with
  `site_capture.py`), photos or clips to a beat-synced reel, on-screen text, the plain-words handover.
- `references/editing-craft.md` - pacing, genre recipes (talking head, beat-synced montage, cinematic
  vlog, product promo, photo slideshow), and the effect/transition/filter palette by mood, with a
  separate Pro palette for CapCut Pro users.
- `references/capcut-notes.md` - what is and is not possible in a generated draft, CapCut-side
  follow-ups, and troubleshooting when a draft does not show up or a resource is missing.

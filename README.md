# cappus

**A Claude Code skill that edits your footage into a CapCut desktop project you can keep editing.**

Ask Claude for an edit in plain language. Instead of a flattened MP4, you get a normal CapCut draft:
every cut, text layer, transition, effect, filter, animation, keyframe and caption sits on the
CapCut timeline, ready for you to adjust and export.

Works with **free CapCut and CapCut Pro**. You choose which one you have, and cappus only uses
resources your account can export.

> Panduan berbahasa Indonesia: [docs/cara-pakai.md](docs/cara-pakai.md)

## Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Choose your plan: Free or Pro](#choose-your-plan-free-or-pro)
- [Usage](#usage)
  - [Captions](#captions)
- [Finishing in CapCut](#finishing-in-capcut)
- [Troubleshooting](#troubleshooting)
- [Running the scripts directly](#running-the-scripts-directly)
- [Updating](#updating)
- [Project structure](#project-structure)
- [Contributing](#contributing)
- [Acknowledgements and disclaimer](#acknowledgements-and-disclaimer)
- [License](#license)

## How it works

1. **Analyze.** Claude inspects your media: contact sheets of each clip, shot changes, pauses in
   speech, a word-by-word transcript of what is said, and the beats of your music.
2. **Plan.** It drafts the edit (hook, body, payoff) and writes it as an *edit spec*, a JSON file
   with times in seconds.
3. **Validate.** `build_draft.py` checks the spec against a catalog of real CapCut resources and
   reports every problem at once.
4. **Write.** The builder writes the draft straight into CapCut's drafts folder. Claude then tells
   you what it did, what it could not do, and what to check first.

Every transition, effect, filter, animation and font is referenced by CapCut's internal ID, taken
from a catalog of about 5,000 resources (about 1,200 free and 3,800 Pro). The builder rejects names
that are not in the catalog. It also rejects about 380 catalog items that CapCut has withdrawn, so
your draft never shows a missing effect or an "animation loss" label.

## Requirements

| Requirement | Notes |
|---|---|
| CapCut desktop (international edition) | Tested with CapCut 8.0.1 and 9.8.0 on Windows. macOS uses the same draft format but has not been tested yet. JianYing (the Chinese edition), CapCut mobile and CapCut web are not supported. |
| Claude Code | The CLI, the Code tab of the Claude desktop app, or an IDE extension. It must run **on the same computer as CapCut**, because drafts are written to CapCut's local drafts folder. Claude.ai chat and cloud sessions cannot do this. |
| Python 3.9 or later | Used by the bundled scripts. |
| ffmpeg and ffprobe | Must be on your `PATH`. Used to analyze media. |
| faster-whisper (optional) | Only for captions from speech. Runs offline; the first use downloads a speech model of about 0.5 GB. |

## Installation

### 1. Install the skill

**Option A: as a plugin (recommended).** Run these in your terminal:

```bash
claude plugin marketplace add nsudy-code/cappus
```

```bash
claude plugin install cappus@cappus
```

Or run the same steps inside a Claude Code session: `/plugin marketplace add nsudy-code/cappus`,
then `/plugin install cappus@cappus`, and choose a scope. A user-scope install is available in the
terminal, the desktop app and VS Code on the same computer.

**Option B: from a clone.** Use this if you want to contribute, or to update with `git pull`:

```bash
git clone https://github.com/nsudy-code/cappus.git
```

Then link the skill folder into Claude's skills directory. On Windows (PowerShell), from the folder
that contains the clone:

```powershell
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\capcut-editor" -Target "$PWD\cappus\skills\capcut-editor"
```

On macOS or Linux:

```bash
mkdir -p ~/.claude/skills && ln -s "$PWD/cappus/skills/capcut-editor" ~/.claude/skills/capcut-editor
```

Use one option, not both. With both, Claude sees the skill twice.

### 2. Install the Python dependencies

```bash
python -m pip install "pycapcut==0.0.4" numpy
```

From a clone you can run `python -m pip install -r skills/capcut-editor/requirements.txt` instead.
`pycapcut` writes the draft files, and `numpy` is used for beat detection. If they are missing,
Claude installs them on first use.

**Optional: captions from speech.**

```bash
python -m pip install faster-whisper
```

This adds offline speech-to-text (Whisper). It is only needed for captions and transcript-based
cutting. If it is missing when you ask for captions, Claude offers to install it. The first
transcription downloads the default `small` model (about 0.5 GB); after that no network is needed.

### 3. Check the installation

Start a **new** Claude Code session (skills load when a session starts) and ask:
"Is the capcut-editor skill available?" With the plugin install, the skill also appears as
`/cappus:capcut-editor` when you type `/`.

## Choose your plan: Free or Pro

CapCut offers free resources and Pro (paid) resources. A draft that uses Pro items opens and
previews in any account, but only a CapCut Pro account can export it. cappus therefore needs to
know which plan you have.

| | Free (default) | Pro |
|---|---|---|
| Resources available | About 1,200 free items | The full catalog, about 5,000 items |
| Curated picks with English names | About 490 | About 490, plus about 390 Pro picks: film looks, camera-move effects, light leaks, refined text animations and fonts |
| Background removal in the draft | No | Yes (CapCut's Auto removal) |
| Export | Always works | The exporting account needs CapCut Pro |

**How to choose:**

- **Answer once.** On first use, Claude asks whether you have CapCut Pro and remembers your answer.
  Until you answer, it uses free resources only.
- **Tell Claude at any time.** Say "I use the free version of CapCut" or "I have CapCut Pro".
  Claude saves the setting and uses it from then on.
- **Set it yourself.** From a clone, run `python skills/capcut-editor/scripts/tier.py free` or
  `... tier.py pro`. Run `tier.py` with no argument to see the current setting.

The setting is stored per user in `~/.cappus/config.json`. The environment variable
`CAPPUS_TIER=free` or `CAPPUS_TIER=pro` overrides it, which is useful on shared machines.

**One draft for a free account.** If you have Pro but a draft will be exported by someone on free
CapCut, say so ("this one will be exported from a free account"). Claude builds that draft with
free resources only.

## Usage

Ask Claude in plain language. Name the files or folder, where the video is going, the rough
length and the style. Claude fills in sensible defaults (vertical 1080x1920 at 30 fps for
short-form) and states its assumptions instead of asking a list of questions.

Example requests:

> Edit the clips in D:\Trips\Bali into a 20-second vertical reel synced to song.mp3. Cinematic
> look, with a title at the start.

> Cut the dead air and the repeated takes out of interview.mp4, add word-by-word captions, and keep
> it under 60 seconds for YouTube Shorts.

> Make a 15-second product ad from the photos and clips in D:\Products\Coffee. Hook in the first
> two seconds, a short label for each feature, and end on logo.png.

> Turn the photos in D:\Wedding into a 45-second slideshow with gentle motion on every photo,
> timed to music.mp3.

### Opening the result

Open CapCut. The draft appears in your project list under the name Claude reports. If CapCut was
already open, go back to the home screen or restart CapCut so it rescans its drafts.

Media is **linked, not copied**. Do not move, rename or delete the source files, or CapCut will
show them as offline.

### Captions

For footage with speech, Claude transcribes it offline and writes the captions into the draft as
ordinary CapCut text, styled and editable. Each word keeps its time in the source file, so the
captions stay in sync after Claude removes pauses, drops repeated takes or reorders sentences. Tell
Claude how to spell names, brands and unusual terms. If a word is wrong, fix it in CapCut or ask
Claude to transcribe again with the more accurate `large-v3-turbo` model (about 1.6 GB, slower).
If you already have an SRT file, give it to Claude instead.

### Revisions

Ask for changes in the same way: "make the title smaller", "swap the second and third clips",
"less saturated". Claude edits the spec and rebuilds the draft.

- Claude only overwrites drafts that cappus created. Your other CapCut projects are never touched.
- Before rebuilding, Claude checks whether you edited the draft in CapCut. If you did, it asks
  before overwriting, or saves the new version under a different name.
- Close the draft in CapCut (return to the home screen) before a rebuild.

## Finishing in CapCut

Some features cannot be written into a draft. Each takes one or two clicks in CapCut:

| You want | In CapCut |
|---|---|
| Speed ramp (curve speed) | Select the clip > Speed > Curve |
| Auto captions without installing faster-whisper | Text > Auto captions (with faster-whisper, Claude adds the captions itself; see [Captions](#captions)) |
| Remove the background by brush | Select the clip > Video > Remove BG > Custom removal (with Pro, Claude can turn on Auto removal in the draft itself) |
| Eased keyframes | Click a keyframe and choose an easing preset (drafts use linear keyframes) |
| Color wheels, HSL, curves, LUTs | Select the clip > Adjust |
| Sound effects and CapCut's music library | Audio > Sound effects / Music |
| Export | Export button, top right |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| The draft is not in the project list | CapCut was open during the build. Return to the home screen or restart CapCut. If you changed CapCut's drafts location, tell Claude where it is. |
| "Animation loss", a missing effect icon, or a font that falls back to the default | CapCut no longer serves that resource. Open the draft once, return to the home screen, and tell Claude. It runs `check_resources.py read`, replaces the items, rebuilds, and records them so they are not used again. Please [report it](https://github.com/nsudy-code/cappus/issues/new/choose) so everyone gets the fix. |
| An effect shows a download spinner | CapCut downloads each resource the first time it is used. Stay online and wait. |
| "Media offline" | The source files were moved or renamed. Relink them in CapCut, or tell Claude the new location. |
| The draft opens with an empty timeline | Your CapCut version may store drafts differently. Please [open a bug report](https://github.com/nsudy-code/cappus/issues/new/choose) with your CapCut version (Settings > About). |
| Pro items in a draft you cannot export | Your plan is set to Pro, or the draft was built for Pro. Tell Claude "I use the free version of CapCut" and ask it to rebuild the draft. |

## Running the scripts directly

Claude runs these for you, but you can also use them yourself from a clone. Every script prints
JSON and has `--help`.

| Script | Purpose |
|---|---|
| `probe.py` | Media info, contact sheets, shot changes, speech segments, music beats |
| `transcribe.py` | Speech to text with a time for every word, plus an optional SRT (needs faster-whisper) |
| `catalog.py` | Search the CapCut resources: transitions, effects, filters, animations, fonts |
| `build_draft.py` | Validate a spec (`--check`) and write it as a CapCut draft |
| `inspect_draft.py` | Read an existing draft, including your manual edits in CapCut |
| `tier.py` | Show or set your CapCut plan (free or Pro) |
| `check_resources.py` | Find catalog items CapCut can no longer load |

Try the bundled demo:

```bash
python examples/make_test_media.py
```

```bash
python skills/capcut-editor/scripts/build_draft.py examples/demo.json --check
```

```bash
python skills/capcut-editor/scripts/build_draft.py examples/demo.json --overwrite
```

Then open the `cappus-demo` draft in CapCut. `examples/demo-pro.json` shows Pro resources and needs
`--allow-pro` or a Pro setting.

## Updating

- **Plugin install:** run `claude plugin update cappus@cappus`, or open `/plugin` in a session, go
  to the **Installed** tab, select cappus and choose **Update now**. Plugins from this marketplace
  do not update automatically unless you turn on auto-update for it on the **Marketplaces** tab.
- **Clone install:** run `git pull` in the clone.

Updates also bring the latest list of resources CapCut has withdrawn, so update when you see
"animation loss". Start a new Claude Code session after updating.

## Project structure

```
skills/capcut-editor/
  SKILL.md                  Instructions Claude follows
  references/
    edit-spec.md            Edit spec format (JSON)
    editing-craft.md        Pacing, genre recipes, effect palettes by mood (free and Pro)
    capcut-notes.md         Limits, CapCut follow-ups, troubleshooting
  scripts/
    probe.py                Media analysis
    transcribe.py           Speech to text with word timings (optional)
    catalog.py              Resource search
    build_draft.py          Spec to CapCut draft
    inspect_draft.py        Read existing drafts
    tier.py                 Free or Pro setting
    check_resources.py      Detect resources CapCut no longer loads
    aliases.json            ~490 curated free resources with English aliases
    aliases_pro.json        ~390 curated Pro resources with English aliases
    unavailable.json        Resources CapCut has withdrawn; the builder rejects them
  requirements.txt
  requirements-captions.txt Optional speech-to-text dependency
docs/cara-pakai.md          User guide in Indonesian
examples/                   Demo specs and a synthetic media generator
.claude-plugin/             Plugin and marketplace manifests
```

## Contributing

Contributions are welcome, especially reports of resources that no longer load in your CapCut
version. Read [CONTRIBUTING.md](CONTRIBUTING.md) before you open a pull request.

## Acknowledgements and disclaimer

Drafts are written with [pycapcut](https://github.com/GuanYixuan/pyCapCut), which is also the source
of the CapCut resource catalog.

cappus is an independent project. It is not affiliated with, endorsed by or sponsored by CapCut or
ByteDance. CapCut is a trademark of its respective owner. CapCut Pro resources require a valid
CapCut Pro subscription to export.

## License

[MIT](LICENSE)

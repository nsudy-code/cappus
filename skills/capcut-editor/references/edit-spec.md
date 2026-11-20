# Edit spec reference

One JSON object. All times are **seconds**. Unknown keys are rejected (typos get caught), except
`"note"`, which is allowed on every item for your own comments.

## Contents

- [Top level](#top-level)
- [Time values and references](#time-values-and-references)
- [Coordinates and scale](#coordinates-and-scale)
- [video - main track clips](#video---main-track-clips)
- [Eased keyframes](#eased-keyframes)
- [overlays - picture-in-picture, B-roll, layers](#overlays)
- [audio](#audio)
- [sfx - sound effects](#sfx---sound-effects)
- [texts and styles](#texts-and-styles)
- [captions](#captions)
- [effects and filters on their own tracks](#effects-and-filters-on-their-own-tracks)
- [stickers](#stickers)
- [Resource names and parameters](#resource-names-and-parameters)

## Top level

| key | default | meaning |
|---|---|---|
| `name` | spec file name | Draft name shown in CapCut. Also the folder name. |
| `width`, `height` | 1080, 1920 | Canvas. 9:16 = 1080x1920, 16:9 = 1920x1080, 1:1 = 1080x1080, 4:5 = 1080x1350. |
| `fps` | 30 | Match the footage when it is consistently 24/25/60. CapCut projects run at 24, 25, 30, 50 or 60; any other value (29.97, 59.94) is rounded to the nearest with a warning. |
| `allow_pro` | user's plan | Omit it normally: Pro is then allowed exactly when the user's saved plan is Pro (`tier.py`). Set `false` to force a free-only draft (e.g. it will be exported from a free account), `true` only if the user has Pro but it is not saved. |
| `look` | none | A tested look (`looks.py` lists them): adds the styles `title`, `accent`, `big`, `label` and `caption`, and captions use `caption` by default. Spec `styles` with the same name override the look's key by key. |
| `fonts` | look's pairing | `{"headline": "bebas", "body": "kilig"}`: swap the look's fonts for another curated pairing (see `looks.py <look>`, `pairings`). Sizes are scaled by the fonts' measured widths. Only with `look`. |
| `brand` | look's colors | `{"accent": "#F59E0B", "text": "#FFFFFF", "muted": "#94A3B8"}`: the brand colors the look's styles use. Only with `look`. |
| `styles` | {} | Named text styles, reused via `"style": "<name>"`. |
| `linear_keyframes` | false | `true` writes every eased curve (keyframe `ease`, motion presets) as several linear keyframes instead of a CapCut curve: the fallback for a CapCut build that shows the curves wrong. |
| `video` | required | Main-track clips, in playback order. |
| `overlays`, `audio`, `sfx`, `texts`, `captions`, `effects`, `filters`, `stickers` | [] | See below. |

## Time values and references

Anywhere a timeline time is expected (`at`, `end`, duck ranges):

| form | meaning |
|---|---|
| `4.5` | seconds from timeline start |
| `"1:04.5"` | minutes:seconds |
| `"@hook"` / `"@hook.start"` | start of the clip whose `id` is `hook` |
| `"@hook.end"` | its end |
| `"@hook+0.4"`, `"@hook.end-0.25"` | offset in seconds |
| `"end"`, `"end-1.5"` | end of the main track |

`duration` is a length in seconds, or `"@hook"` meaning "as long as that clip".
Give either `duration` or `end`, not both. Ids exist for main clips and overlays (and any other item
you give an `id`); an item can only reference ids defined earlier in this order: video, overlays,
audio, texts, captions, effects, filters.

## Coordinates and scale

- Position `x`, `y` is the item's centre in **half-canvas units**: `0,0` is the centre, `x = 1` the right
  edge, `x = -1` the left edge, `y = 1` the **top** edge, `y = -1` the bottom edge.
- `scale` 1.0 = the clip as fitted to the canvas (after `fit`). Text `scale` multiplies its `size`.
- `rotation` is degrees clockwise. `opacity` is 0-1.

Vertical-video safe zone (platform UI covers the rest): keep text within `y` from about `-0.55` to
`0.7`, and `x` within `-0.8` to `0.8`. Captions sit well around `y = -0.45` to `-0.6`; titles around
`y = 0.45` to `0.6`.

## video - main track clips

```json
{"id": "hook", "src": "surf.mp4", "in": 3.2, "out": 5.0, "speed": 1.0, "fit": "cover",
 "volume": 1.0, "motion": "push_in", "transition": {"name": "dissolve", "duration": 0.4}}
```

| key | meaning |
|---|---|
| `src` | Video, image or GIF. Relative paths resolve from the spec file's folder. |
| `in`, `out` | Source range in the file. Defaults: 0 and end of file. |
| `duration` | Videos: timeline length instead of `out`. **Images: how long the still is shown (default 3).** |
| `speed` | 0.1-100. 0.5 = slow motion (needs 60 fps footage to look smooth), 2 = fast. Constant only. |
| `volume`, `mute` | Clip audio gain (1 = original), or `"mute": true`. |
| `fade` | `{"in": 0.3, "out": 0.3}` - fades the clip's **audio**. For a visual fade use `intro`/`outro` `fade_in`/`fade_out`. |
| `fit` | `"contain"` (default, whole frame visible, bars if aspect differs) or `"cover"` (fill canvas, crop overflow). |
| `background` | For `contain`: `"blur"`, `{"blur": 1-4}` or `"#RRGGBB"`. Main track only. |
| `transform` | `{"scale", "scale_x", "scale_y", "x", "y", "rotation", "opacity", "flip_h", "flip_v", "x_path"}` |
| `transform.x_path` | Follow a moving subject: `[[source_seconds, x], ...]`, times rising, as `scan_footage.py` gives it in `reframe_path`. Times are in the **source file** (like `in` / `out`), so the path fits whatever part of the shot the clip plays, at any `speed`; it becomes linear `x` position keyframes on the clip, held at the end values outside the path. Use instead of `x`, not with `keyframes.x` or a pan `motion` (`push_in` / `pull_out` are fine). |
| `motion` | Camera-move preset: `push_in`, `pull_out`, `pan_left`, `pan_right`, `pan_up`, `pan_down`, or `{"type": "push_in", "amount": 0.15}` (default amount 0.12). Runs over the whole clip. |
| `keyframes` | `{"scale": [[0, 1.0], [2.0, 1.2]], "x": [[0, 0], [-0.01, 0.1]]}`. Time is seconds from the clip's start; **negative = from its end**. Properties: `x`, `y`, `scale`, `scale_x`, `scale_y`, `rotation`, `opacity`, `saturation`, `contrast`, `brightness` (last three: -1..1, 0 = unchanged), `volume`. A point may carry an ease as a third value, `[2.0, 1.2, "ease_out"]`, and `"ease"` beside the properties sets it for every point without one (see [Eased keyframes](#eased-keyframes)); otherwise linear. Not with `motion` on the same property. |
| `intro`, `outro` | Clip In/Out animation: `"fade_in"` or `{"name": "zoom_in", "duration": 0.4}` (kinds `video_intro`, `video_outro`). |
| `combo` | Whole-clip Combo animation (kind `video_combo`). Cannot be combined with intro/outro. |
| `transition` | Joins this clip to the **next** one (kind `transition`). Not allowed on the last clip. Duration is capped at half the shorter neighbour. Takes `"sfx"` too: `{"name": "whip_pan", "sfx": "whoosh"}` puts the sound on the cut ([sfx](#sfx---sound-effects)). |
| `sfx` | A sound on the cut into this clip (its start): `"hit"` or `{"sound": "hit", "gain": 2}`. Also on overlays (their start). |
| `filter` | `"teal_orange"` or `{"name": ..., "intensity": 0-100}` - applies to this clip only. |
| `effects` | List of `"name"` or `{"name", "params"}` - scene or body effects on this clip only. |
| `mask` | `{"type": "circle", "x": 0, "y": 0, "size": 0.5, "feather": 10, "rotation": 0, "invert": false}`. Types: `linear`, `mirror`, `circle`, `rectangle`, `heart`, `star`. `x`,`y` in -1..1 of the clip; `size` = fraction of clip height. Rectangle also takes `width` (fraction of clip width) and `round` (0-100). |
| `blend` | Blend mode: `screen`, `overlay`, `multiply`, `soft_light`, `hard_light`, `lighten`, `darken`, `color_dodge`, `color_burn`, `linear_burn`. Meaningful on overlays. |
| `chroma` | Green screen: `{"color": "#00FF00", "intensity": 20, "shadow": 0}`. |
| `adjust` | A constant color correction: `{"brightness": -0.1, "contrast": 0.05, "saturation": 0.08}`, each -1..1 (0 = unchanged). `scan_footage.py` proposes it to make shots match. Not together with `keyframes` on the same property. |
| `remove_bg` | `true` turns on CapCut's Remove BG > Auto removal, which cuts the person or main subject out of a video or image. **CapCut Pro feature**: it is rejected unless Pro is allowed. CapCut computes the cutout the first time the draft opens, a few seconds per clip. Below a cutout on the main track there is only black, so to put someone on a new background, place the background on the main track and the person in an overlay with `remove_bg`. |

## Motion presets: enter and exit

`"enter"` and `"exit"` on main clips, overlays and texts (or in a text style) add eased movement as
one or two keyframe segments with CapCut ease curves (`cubic_out` in, `cubic_in` out, `cubic_in_out`
for a settle), which the user can change on the keyframe in CapCut. A preset
ends exactly on the item's resting transform (or style position), so the item looks the same as
without it once it has played. Give a name, or `{"name": "pop", "duration": 0.4}`.

| enter | on | what it does (default length) |
|---|---|---|
| `pop` | overlays, texts | scales 1% -> 108% -> 100%; overlays also fade in (0.35 s) |
| `punch` | overlays, texts | scales 125% -> 100%, a hard hit for a beat (0.25 s) |
| `rise` | overlays, texts | moves up into place; overlays also fade in (0.35 s) |
| `drop` | overlays, texts | falls into place and settles (0.4 s) |
| `slide_left`, `slide_right` | overlays, texts | comes in from the right / left (0.35 s) |
| `fade` | overlays | opacity 0 -> 1 (0.3 s) |
| `grow_left`, `grow_right` | overlays | width grows from the left / right edge: bars, underlines (0.45 s) |
| `slam` | overlays, texts | scale 190% -> 100%: the word hits the screen (0.12 s) |
| `slam_tilt` | overlays, texts | slam from 210% while untwisting 9 degrees (0.13 s) |
| `whip_left`, `whip_right` | overlays, texts | flies in from beyond the right / left edge (0.15 s) |
| `fall`, `jump` | overlays, texts | drops in from above / shoots up from below (0.14 s) |
| `spin` | overlays, texts | spins in from -120 degrees while growing (0.18 s) |

| exit | on | |
|---|---|---|
| `fade` | overlays | opacity to 0 (0.3 s) |
| `shrink` | overlays, texts | scales to 1% (0.3 s) |
| `sink` | overlays, texts | moves down; overlays also fade out (0.3 s) |
| `slide_left`, `slide_right` | overlays, texts | leaves to the left / right (0.3 s) |
| `zoom_through` | overlays, texts | scales to 14x: the camera flies through the word into the next section (0.26 s) |

Presets combine with `keyframes` and `motion` on the same property: the spec's points inside the
preset's time window are replaced, and the preset's last (or first) point is moved onto the rest of
the curve, so a card can pop in and then keep a slow drift. Texts cannot fade with keyframes; pair a
text `enter` with a catalog `intro` such as `fade_in` when it should also fade.

## Eased keyframes

A keyframe point is `[seconds, value]` or `[seconds, value, ease]`. The ease shapes the segment that
**ends** at that point: `[[0, 1.0], [2, 1.5, "ease_out"]]` grows to 150% and slows into it. An ease on
the first point has no segment to shape and does nothing. `"ease"` next to the properties is the
default for every point without its own: `{"ease": "ease_in_out", "x": [[0, -0.2], [3, 0.2]]}`.
`"linear"` (or no ease) keeps a straight line. Works in every visual `keyframes` (clips, overlays,
texts, stickers) and on `motion`'s points (`{"motion": "push_in", "keyframes": {"ease": "ease_in_out"}}`);
audio volume keyframes stay linear.

| ease | CapCut preset | feel |
|---|---|---|
| `ease_in`, `ease_out`, `ease_in_out` | Ease In, Ease Out, Ease | gentle start / gentle landing / both |
| `quad_in`, `quad_out`, `quad_in_out` | Quad In, Quad Out, Quad Ease | a little stronger |
| `cubic_in`, `cubic_out`, `cubic_in_out` | Cubic In, Cubic Out, Cubic Ease | strong: fast start into a soft landing (`cubic_out`) is the snappy default for hits |
| `circ_in_out` | Circular Ease | very slow ends, fast middle: a whip pan |
| `back_in`, `back_out` | Rebound In, Rebound Out | pulls back before leaving / overshoots and settles (about 10%) |
| `[x1, y1, x2, y2]` | custom curve | a CSS `cubic-bezier`; x1, x2 in 0..1, y may go outside 0..1 to overshoot |

In CapCut a named ease shows as that preset on the keyframe (right-click > Show all presets).
`"linear_keyframes": true` at the top level samples every curve into linear keyframes instead.

## Kinetic typography helpers

- `"drift": 0.05` (texts, text styles, overlays): the item keeps growing slowly, scale 1.0 -> 1.05
  over its whole time on screen, so a held word never looks frozen. Combines with `enter`.
- `"fit_width": 0.86` (text styles): the size is computed so the longest line is that fraction of
  the canvas wide, from the font's measured width (`fonts.json`); `size_max` caps it (default 48).
  Wrapping is turned off unless the style sets `wrap`.
- `"echo": {"count": 4, "spacing": 0.2, "stagger": 0.08}` (texts): repeats the word above and below
  itself (`spacing` in half-canvas units), each copy `stagger` seconds later, as an outline (black
  fill, white stroke; or `"style": "<name>"` / `color` / `stroke` for the copies). `"echo": true`
  uses those defaults.

## Text contrast

For every text over the main track, the builder grabs the frame behind it, measures the area the text
covers, and compares it with the text color (WCAG contrast). Under 3:1 it warns with the color that
would read there; with `"auto"` or a color list it picks one. Where light text still does not reach
3:1 because the footage is busy (fireworks, city lights), it adds a scrim: a soft black gradient
(transparent, 45 %, transparent; `cappus_assets/scrim.png` next to the spec) on a video track behind
that text only, fading in and out with it, shared by a title and its partner line. It says so under
`notes`. No outline and no drop shadow is ever added. A text and the one that comes in with it (within 1.2 s) keep the same
light or dark color. Captions and texts with a stroke of 20 or more or a background box are not
checked.

## Text fit warnings

`--check` estimates how wide each text line is from its font (`scripts/fonts.json`, measured in
CapCut) and warns when a line would wrap onto another line or run off the canvas, with the size
that would fit. The estimate is close for the curated fonts and rough for others; fix the warning by
shortening the line or splitting it across two text items.

## overlays

Same keys as a main clip (no `transition`, no `background`), plus placement:

```json
{"id": "pip", "src": "reaction.mp4", "at": "@hook+0.5", "end": "@hook.end", "mute": true,
 "transform": {"scale": 0.35, "x": 0.58, "y": 0.6},
 "mask": {"type": "rectangle", "size": 0.95, "width": 0.95, "round": 12}, "intro": "slide_left"}
```

`at` is the timeline start. Length comes from `in`/`out`, or `duration`, or `end`. Optional `track`
names the layer (default `"overlay"`); tracks created later sit **above** earlier ones. Typical uses:
B-roll covering a talking head (full-size, `"fit": "cover"`, `"mute": true`), picture-in-picture,
light-leak/dust footage with `"blend": "screen"`, logo PNG in a corner.

## audio

```json
{"src": "song.mp3", "at": 0, "in": 31.5, "end": "end", "volume": 0.6,
 "fade": {"in": 0.2, "out": 1.2},
 "duck": {"ranges": [["@talk", "@talk.end"]], "to": 0.2, "ramp": 0.25}}
```

| key | meaning |
|---|---|
| `src`, `at` | File and timeline start. |
| `in`, `out` | Source range. `in` picks where in the song to start. |
| `duration` / `end` | Timeline length instead of `out`. `"end": "end"` trims to the main track. If the file is too short you get a warning, not a loop - add a second item. |
| `volume` | 1 = original. Music under speech ~0.15-0.3; music alone ~0.5-0.8; voice-over 1.0. |
| `fade` | `{"in", "out"}` seconds. |
| `duck` | Lowers volume to `to` x volume during each timeline range (with `ramp` s slopes) via volume keyframes. |
| `keyframes` | `{"volume": [[t, v], ...]}` - manual automation, t from the item's start. |
| `effects` | Voice/scene effects (kinds `audio_effect`, `voice_effect`), e.g. `"echo"`, `"lofi"`, `"megaphone"`. |
| `speed`, `track` | Playback rate; track name (default `"audio"`, use e.g. `"music"`, `"vo"`). A voice-over goes on a track named `vo...` or `voice...` so it does not count as music for the [sfx](#sfx---sound-effects) level. |

## sfx - sound effects

Generated sounds (or the user's own files), each placed so its **peak lands one frame after the
picture it belongs to**: a whoosh's swell on the cut, a pop on the frame the text appears, a riser's
top on the hit. Three ways to add one:

```json
"video": [{"src": "a.mp4", "transition": {"name": "whip_pan", "sfx": "whoosh"}}, ...],
"texts": [{"text": "SALE", "at": 2.0, "duration": 1.5, "sfx": "pop"}],
"sfx": [{"sound": "riser", "at": "@reveal"}, {"sound": "hit", "at": "@reveal", "gain": 2},
        {"src": "media/door.wav", "peak": 0.42, "at": 7.5}]
```

`"sfx"` on a transition goes on the cut (the middle of the transition), on a clip or overlay at its
start, on a text at its `at` (once, not again for each `echo` copy). The top-level list needs `at`
and can point anywhere.

| key | meaning |
|---|---|
| `sound` | A generated sound: `whoosh` (3 takes), `pop` (2), `tick` (2), `hit` (2), `riser` (1, 2 s, peaks at its end). |
| `src`, `peak` | Instead of `sound`: the user's own file and the seconds into it where it should land (default 0). |
| `at` | Top-level list only: the picture time. The sound's peak plays one frame later. |
| `take` | 1-based take. Default: repeats of a sound rotate through its takes in time order, so two whooshes in a row differ. |
| `volume` | Absolute gain. Default: the loudest music playing at that moment +3 dB (1.41 with no music). Audio on tracks named `sfx...`, `vo...` or `voice...` is not counted as music; `duck` is not taken into account. Capped at 4 (+12 dB). |
| `gain` | dB on top of that, -40..20. `-3` for a softer whoosh on a gentle dissolve, `+2` for the one hit that matters. |
| `track`, `id` | Track name (default `"sfx"`, more lanes are added as sounds overlap); `id` for references (top-level list only). |

A sound whose lead-in would start before 0 starts at 0 with the lead-in cut off; one whose tail runs
past the end of the main track is trimmed there. The kit is generated by `scripts/sfx.py` into
`~/.cappus/sfx` on first use (well under a second) and is free to use anywhere. Like all media it is
linked, not copied, into the draft.

## texts and styles

```json
"styles": {
  "title": {"font": "Poppins_Bold", "size": 14, "bold": true, "color": "#FFFFFF", "y": 0.5,
            "stroke": {"color": "#000000", "width": 45},
            "intro": {"name": "zoom_in", "duration": 0.3}, "outro": "fade_out"}
},
"texts": [
  {"text": "3 THINGS I WISH\nI KNEW", "at": 0.2, "end": "@hook.end", "style": "title"},
  {"text": "#2", "at": "@two", "duration": 1.2, "style": "title", "size": 22, "color": "#FFE600"}
]
```

A text item takes `text` (use `\n` for line breaks), `at`, `duration`/`end`, optional `track`, optional
`style` (a name from `styles`, or an inline object), and any style key directly - direct keys override
the style.

| style key | default | meaning |
|---|---|---|
| `font` | system | Kind `font` (`catalog.py font <keyword>`). Check the font covers your language. |
| `size` | 8 | CapCut font size. On 1080x1920: captions 7-10, titles 12-18, single big words 20-30. A first guess - tell the user to eyeball it. |
| `color` | `#FFFFFF` | `#RRGGBB`; `"auto"` (white or dark, whichever reads over the footage behind it); or a preference list such as `["#FFA16B", "#FFFFFF", "auto"]`: the first that reaches 3:1 contrast. Looks use lists, so an accent falls back to white or dark where it would wash out. |
| `bold`, `italic`, `underline` | false | |
| `align` | `center` | `left`, `center`, `right`. |
| `wrap` | 0.82 | Max line width as a fraction of canvas width; `false` disables wrapping. |
| `letter_spacing`, `line_spacing` | 0 | CapCut units. |
| `x`, `y`, `scale`, `rotation`, `opacity` | 0, 0, 1, 0, 1 | Placement (see coordinates). |
| `stroke` | none | `{"color": "#000000", "width": 0-100, "opacity": 1}` - width 30-50 is a solid outline. |
| `shadow` | none | `{"color", "opacity", "blur", "distance", "angle"}`. |
| `background` | none | Box behind text: `{"color": "#000000", "opacity": 0.6, "radius": 0.3}`. |
| `intro`, `outro` | none | Kinds `text_intro`, `text_outro`; name or `{"name", "duration"}`. |
| `loop` | none | Kind `text_loop`; runs between intro and outro. |
| `keyframes` | none | On the text item (not in a style): `x`, `y`, `scale`, `rotation`. |
| `enter`, `exit` | none | Motion presets (see above): `pop`, `punch`, `rise`, `drop`, `slide_left`, `slide_right`; exits `shrink`, `sink`, `slide_left`, `slide_right`. |
| `effect_id`, `bubble` | none | Fancy-text / bubble presets by raw CapCut id - see `capcut-notes.md`. |

## captions

Burned-in style subtitles as individual editable text segments. Exactly one source:

```json
"captions": {"transcript": "talk.transcript.json", "style": "caption", "uppercase": true}

"captions": {"srt": "talk.srt", "source": "talk.mp4", "style": "caption"}

"captions": {"cues": [{"start": 0.4, "end": 1.9, "text": "Okay so here's the thing"}], "style": "caption"}

"captions": {"words": [{"word": "Okay", "start": 0.40, "end": 0.62}, ...],
             "max_words": 3, "max_chars": 18, "style": "caption"}
```

| Key | Default | Meaning |
|---|---|---|
| `transcript` | - | A `*.transcript.json` from `transcribe.py`. Its words are used, and its media file becomes `source`. |
| `words`, `srt`, `cues` | - | Word timings, an SRT file, or ready-made cues. |
| `source` | from `transcript`, else none | The media file the times refer to. See below. `null` = the times are timeline seconds. |
| `max_words`, `max_chars` | 3, 18 | Cue size when building from words (`transcript` or `words`). |
| `max_gap` | 0.6 | A pause longer than this starts a new cue. Shorter pauses keep the cue on screen. |
| `uppercase` | false | Show the text in capitals. |
| `punctuation` | true | `false` strips `. , ! ? ; :` from what is shown (decimals and times like `10:30` stay). |
| `offset` | 0 | Extra shift in seconds, applied last. |
| `min_duration` | 0.35 | Shortest time a cue stays on screen. |
| `style`, `track` | caption look, `"captions"` | As for texts. Default look: size 9, bold, white, black stroke, `y = -0.6`. |

**Source times and the timeline.** With a `source`, every time is a position in that file, and the
builder places each word through the clips that play it with sound (main track, overlays and audio
items, using their `in`/`out`, position and `speed`). So when you cut a talk into jump cuts, reorder
sentences or speed a clip up, the captions follow without any arithmetic. A word goes where its
middle falls; words in parts you cut are left out (the `--check` timeline says how many). A cue never
spans a cut. SRT/cue lines that span a cut are split, one piece per clip. If no audible clip plays the
source, the build stops with an error: unmute or add the clip, or set `"source": null`.

Without a `source` (inline `words`, `srt` or `cues` and no `source` key), times are **timeline**
seconds, shifted by `offset`.

Grouping from words: a new cue starts at `max_words`, `max_chars`, a pause longer than `max_gap`,
punctuation (`. ? ! , ; :`) or a cut. A short joining word such as "the", "and", "yang" or "di" moves to
the start of the next cue instead of ending one. Languages written without spaces (Chinese, Japanese,
Thai, ...) are joined without spaces when the transcript says so.

`captions` may also be a list of such objects, for example two languages on two tracks.

## effects and filters on their own tracks

These sit above the video and affect everything under them for their time range - use them for a look
across several clips or a hit at a specific moment.

```json
"effects": [{"name": "cinematic_bars", "at": 0, "end": "end"},
            {"name": "shake", "at": "@drop", "duration": 0.5, "params": {"speed": 60}}],
"filters": [{"name": "teal_orange", "at": 0, "end": "end", "intensity": 55}]
```

`effects` resolve against `scene_effect`, then `character_effect`. Overlapping items get extra lanes.

## stickers

`{"resource_id": "7226264888031694091", "at": 2, "duration": 2, "transform": {"scale": 0.4, "y": 0.5}}`.
There is no sticker catalog; ids must come from an existing draft (see `capcut-notes.md`). Usually it is
better to tell the user to drop stickers in by hand.

## Resource names and parameters

Any name field accepts the English alias or the original CapCut name, case/space/underscore-insensitive.
Pro resources are rejected unless Pro is allowed (saved plan `pro`, `allow_pro: true`, or
`--allow-pro`), and the error lists free alternatives. `--free-only` forces a free build.

`params` drive the effect's sliders, each **0-100** like in CapCut's UI. Give a list in catalog order
(`null` keeps a default) or an object keyed by parameter name:

```bash
python <skill>/scripts/catalog.py scene_effect chromatic --params
# chromatic   色差   free   params: horizontal_chromatic, vertical_chromatic
```
```json
{"name": "chromatic", "params": {"vertical_chromatic": 40}}
{"name": "chromatic", "params": [null, 40]}
```

Without `params`, CapCut's defaults are used - usually a good starting point. Lower values (20-40)
are the usual fix for an effect that is too strong.

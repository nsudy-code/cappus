# Editing craft

How to make an edit that feels intentional, using only things CapCut has. You will not see the render,
so lean on these rules and on what you saw in the contact sheets.

## Contents

- [Principles](#principles)
- [Pacing numbers](#pacing-numbers)
- [Structure: hook, body, payoff](#structure-hook-body-payoff)
- [Genre recipes](#genre-recipes)
- [Palette by mood](#palette-by-mood)
- [Pro palette (CapCut Pro users)](#pro-palette-capcut-pro-users)
- [Text and captions](#text-and-captions)
- [Sound](#sound)
- [Reframing between aspect ratios](#reframing-between-aspect-ratios)
- [Cheap-looking mistakes to avoid](#cheap-looking-mistakes-to-avoid)
- [Self-review before building](#self-review-before-building)

## Principles

1. **Every cut has a reason**: new information, a beat in the music, a reaction, a change of energy.
   If you cannot name the reason, the clip is too long or should not be there.
2. **Enter late, leave early.** Start a shot just before the action peaks, cut before it settles.
   Choose `in` a few frames before the motion in the contact sheet, not at the start of the file.
3. **Cut on motion.** A cut hidden inside movement (a turn, a hand passing the lens, a whip pan) feels
   seamless. Matching direction of movement across a cut feels even better.
4. **Contrast drives attention.** Alternate wide and close, slow and fast, still and moving.
   Five similar wide shots in a row feel like one long boring shot.
5. **One visual language.** Pick a single look (one filter family at the same intensity), one or two
   transition families, one font pairing, two or three colors. Consistency is what makes it look
   "edited" instead of "decorated".
6. **Effects are punctuation.** Use them at the moments that matter (the drop, the reveal, the punchline)
   and leave the rest clean. An effect on every clip has the same impact as none.

## Pacing numbers

| context | typical shot length |
|---|---|
| Hook (first 1-3 s of short-form) | 0.4-1.2 s per shot, or one striking 2 s shot with text |
| Hype / beat montage | 1 beat (0.4-0.6 s at 100-140 BPM), longer shots every 4-8 beats for breathing room |
| Travel / lifestyle vlog | 1.5-3 s; hero shots 3-5 s |
| Cinematic / emotional | 3-6 s, slower speed (0.5-0.8 with 60 fps source) |
| Talking head | cut every pause; punch-in (scale 1.15-1.3) every 5-10 s or at each new point |
| Product promo | 1-2 s per feature, hold 2-3 s on the hero/end card |
| Photo slideshow | 1.5-3 s per photo, synced to beats when there is music |

Short-form length: 7-15 s for a single-idea clip, 20-45 s for a story or listicle, under 60 s unless
the user asks. Trim more than feels comfortable; the first draft is almost always too long.

## Structure: hook, body, payoff

- **Hook (0-2 s)**: the best visual or the most intriguing line, never a logo or a slow fade from
  black. Text on screen stating the promise ("3 spots locals don't tell you about"). Movement from
  frame one: a `push_in`, a fast clip, a zoom-in intro.
- **Body**: deliver the promise in clear steps. Each step gets a visual change (new shot, punch-in,
  number on screen). Build energy towards the end; save the second-best shot for last.
- **Payoff / end**: the result, the reveal, the punchline, or a loopable last frame. Short-form often
  works better with a clean cut than with a fade, because a loop rewatches cleanly. For long-form or
  emotional pieces, fade the music and finish on a held shot with `fade_out`.

## Genre recipes

### Beat-synced montage (travel, event, sport, "photo dump")

1. `probe.py song.mp3 --beats`. Choose a song section: start `in` just before a strong downbeat or
   an energy jump in `energy_per_second`.
2. Convert beats to timeline times (`beat - in`). Clip lengths = beat intervals: mostly 1-2 beats,
   a 4-beat hold on hero shots, double-time (half-beat cuts) for a burst just before the drop.
3. Because main clips play back to back, give each clip a `duration` (or `out - in`) equal to the gap
   between the beats it spans. Compute these numbers; do not eyeball them. Rounding errors add up -
   recompute from the beat list for each clip instead of adding fixed lengths.
4. On the drop/downbeat: a hard cut to the best shot plus one hit, e.g. a `shake` or `flash_white`
   effect for 0.2-0.4 s, or `white_flash` / `glitch` / `whip_horizontal` transition (0.2-0.3 s).
5. Light consistent look: one filter at 40-70 intensity on its own track across the whole piece.
6. Mute clip audio unless there is a moment worth hearing; music fades out over the last 0.5-1.5 s.

### Talking head / explainer / podcast clip

1. `transcribe.py talk.mp4` and `probe.py talk.mp4 --silence`. Read the transcript like a script:
   mark the sentences worth keeping, the flubbed takes (a sentence said twice - keep the last clean
   one), the false starts and long "umm" stretches. Whisper often leaves fillers out of the text, so
   a gap between two word times with sound in it (`sound_segments`) is usually a filler or a breath.
2. Each kept stretch becomes its own main clip with the same `src` - that is a jump cut. Put `in` about
   0.08-0.15 s before the first word's `start` and `out` the same after the last word's `end`, and
   check against `sound_segments` so no word is clipped. Cut between words, never inside one.
3. Alternate framing at each jump: odd clips `transform.scale` 1.0, even clips 1.15-1.25 (centered on
   the face; adjust `y` so the head is not cropped). Hides the jump and adds energy.
4. Captions: `{"transcript": "talk.transcript.json"}` with `max_words` 2-4, uppercase or bold,
   high-contrast stroke, placed in the lower-middle. They follow the cuts automatically. Highlight
   keywords with a separate text item in an accent color if it fits.
5. B-roll overlays over the main clip when the speaker mentions something showable; mute them.
6. Hook: start on the most interesting sentence, even if it is from the middle (reorder clips).
7. No music, or quiet music (volume 0.1-0.2) ducked under speech.

### Cinematic vlog / mood piece

1. Fewer, longer shots. Slow motion (`speed` 0.5-0.7) on 60 fps footage only; check `fps` from probe.
2. 2.35:1 feel: `cinematic_bars` effect across the piece (horizontal canvas), or none on vertical.
3. Look: `teal_orange`, `film`, `gold200`, `kraft`, `soft_grain` - one of them at 40-70.
   Optional subtle `noise` or `film_leak` overlay effect at low parameters.
4. Transitions: mostly hard cuts; `dissolve` 0.5-1.0 s between time/place changes; `fade_black` for
   the ending. Motion presets (`push_in`, slow pans with amount 0.05-0.1) on static shots.
5. Minimal text: a small, wide-tracked title (`letter_spacing` 2-6, thin or serif font), fade in/out.

### Product promo / ad

1. Hook with the product in action or the problem it solves, not the logo.
2. One feature per shot, with a short text label (2-4 words) and a clean intro like `zoom_in` or
   `slide_up`; consistent position for every label.
3. Punchy transitions on beats: `push_left`/`slide_left` families, `zoom`-style intros, `glitch` only if
   the brand is techy.
4. End card: product + call to action held 2-3 s; logo PNG as an overlay.
5. Brand colors in text; filter only if it flatters the product colors (check skin tones and product
   color in the sheet).

### Photo slideshow / memories

1. Every still gets motion - alternate `push_in`, `pull_out`, `pan_left`, `pan_right`.
   `"fit": "cover"` for full-bleed; `contain` + `"background": "blur"` for photos that must not be
   cropped (group photos).
2. 2-3 s each, on beats. `dissolve` or `blur` transitions (0.5 s) for warm/nostalgic, hard cuts for fun.
3. Warm look: `warm_yellow`, `peach`, `retro`, `1980`, or `old_photo`/`film_frame` effect for nostalgia.
4. Titles with dates/places in a handwritten or serif font.

## Palette by mood

All names below are aliases from the catalog (free). Search for more with `catalog.py`.

| mood | transitions | scene effects | filters | text animations |
|---|---|---|---|---|
| Hype / energetic | `white_flash`, `whip_horizontal`, `glitch`, `shake`, zoom-style intros (`dynamic_zoom_in`) | `shake`, `flash_white`, `strobe`, `chromatic_glitch`, `beat_shots`, `repeat_zoom` | `vivid`, `high_saturation`, `cyberpunk` | `punch_in`, `zoom_in`, `glitch`, loop `word_pop` |
| Clean / modern | `slide_left`, `push_left`, `wipe_left`, `blur` | `slight_zoom`, `light_shake` (low) | `clear`, `natural`, `cool` | `slide_up`, `fade_in`, `reveal_up`, `dissolve_in` |
| Cinematic | `dissolve`, `fade_black`, `blur`, `light_beam` | `cinematic_bars`, `film`, `noise` (low), `film_leak`, `vignette` | `teal_orange`, `gold200`, `dunkirk`, `kraft` | `fade_in`, `blur_in`, letter-spaced titles |
| Retro / nostalgic | `old_film`, `retro_projector`, `memory`, `shutter` | `retro_dv`, `dv_texture`, `bw_vhs`, `old_photo`, `70s`, `1998`, `tv_on` | `vhs`, `1980`, `retro`, `sepia`, `silent_film` | `typewriter`, `flicker` |
| Dreamy / soft | `dissolve`, `glare_dissolve`, `blur`, `bloom` | `dream`, `soft_light`, `halo`, `sparkle`, `petals`, `fireflies` | `peach`, `gentle`, `milk_green`, `white_tea` | `blur_in`, `fade_in`, loop `float` |
| Techy / glitch | `glitch`, `color_glitch`, `chromatic_glitch`, `mosaic` | `chromatic`, `bend_glitch`, `snow_glitch`, `glitch_lines`, `interlace` | `cyberpunk`, `cold_blue`, `night_vision` | `glitch`, `glitch_typewriter`, loop `glitch_flicker` |
| Funny / meme | `spin_cw`, `quake`, `bounce` | `shake`, `fisheye`, `big_head` (character), `question_marks`, `freeze_frame` | none | `somersault`, `elastic`, loop `random_bounce` |

Effect durations: hits 0.2-0.6 s; atmosphere (grain, bars, light leaks) for whole sections.
Transition durations: 0.2-0.4 s for fast/hype, 0.4-0.8 s for clean, 0.6-1.2 s for dissolves.

## Pro palette (CapCut Pro users)

Use this only when Pro is allowed (`tier.py` says `pro`). Pro is not a reason to add more effects:
the same restraint applies. What Pro adds is better versions of the same jobs, such as film-stock
looks, real camera-move effects, light leaks and more refined text animations. Mix freely with the
free palette above and pick whichever item fits the shot best. All names are aliases from
`aliases_pro.json`. They were chosen by name, so check the first use of any pick in the preview.

Every curated item in both palettes (animations, fonts, transitions, effects and filters) was
checked in CapCut 9.8.0 with `check_resources.py`. Items that failed are rejected by the builder, so
a rejection means "pick another", not "fix the name".

| mood | transitions | scene effects | filters | text animations |
|---|---|---|---|---|
| Hype / energetic | `snap_zoom`, `zoom_shake`, `whip_tear`, `hyper_zoom`, `power_zoom`, `shockwave` | `camera_beats`, `beat_zoom`, `beat_pull`, `hard_strobe`, `flash_cam`, `glitch_burst` | `hd_enhance`, `pop_90s` | `spring`, `random_drop`, `chromatic_trail`, loop `zoom_pulse` |
| Clean / modern | `quick_zoom`, `blur_pan`, `swipe_left`, `smooth_fade`, `lens_blur` | `soft_glow`, `depth_sweep`, `fluted_glass`, `window_light` | `clean_white`, `enhance`, `premium_gray` | `letter_reveal`, `feather_wipe_right`, `glow_scan` |
| Cinematic | `film_burn`, `light_leaks`, `lens_flare`, `long_exposure`, `smooth_fade` | `hollywood_glow`, `bokeh_leak`, `film_leak_3`, `tyndall_focus`, `golden_hour` | `cinematic_dusk`, `kodak_500t`, `wong_kar_wai`, `oppenheimer`, `dark_cinema`, `blue_hour` | `letter_reveal`, `blur_glow` |
| Retro / nostalgic | `film_roll`, `film_cut`, `retro_leak`, `retro_film`, `tv_flicker` | `vhs_tape`, `vx1000`, `ccd`, `digicam`, `old_documentary`, `film_border` | `kodak_gold200`, `fuji`, `retro_90s`, `throwback`, `yellowed`, `friends_90s` | `retro_typewriter`, `cursor_type`, loop `vhs` |
| Dreamy / soft | `star_dissolve`, `soft_breath`, `dreamy_shift`, `cloud_reveal` | `dreamy_shimmer`, `dream_fireflies`, `star_bloom`, `petal_rain`, `bokeh`, `glitter` | `sun_drenched`, `dewy_skin`, `before_sunset`, `warm_sun` | `twinkle`, `golden_dust`, loop `shine` |
| Techy / glitch | `digital_matrix`, `hologram`, `liquid_glitch`, `tv_glitch`, `laser_cut` | `cyber_glitch`, `holo_scan`, `aurora_scan`, `liquid_metal`, `neon_edge` | `cyber_2077`, `cyber_blue`, `tokyo_night`, `neon` | `glitch_flash`, `laser_engrave`, `chromatic_trail`, loop `glitch_flicker` |
| Fun / social | `comic_tear`, `comic_panels`, `photo_collage`, `polaroid`, `magic_heart` | `speed_lines`, `comic_frame`, `notification`, `like_post`, `heart_burst` | `pop_90s`, `barbie` | `wave_bounce`, `random_drop`, out `wave_pop`, loop `light_bounce` |
| Food / product | `quick_zoom`, `before_after`, `compare_split` | `close_up`, `closeup_push`, `color_splash`, `hdr` | `hd_food`, `hd_enhance`, `clean_white` | `feather_wipe_right`, `spring` |

Pro camera-move scene effects (`handheld`, `follow_cam`, `push_pull`, `dolly_back`, `close_up`,
`orbit_360`, `zoom_cam`) are an alternative to the `motion` presets on static shots. Use one per
shot, never together with `motion` on the same clip, and keep their intensity sliders low (30-50).

Pro fonts with an alias (`catalog.py font`): `chonk`, `bulgera`, `power_pow` for bold
headlines; `elegant_script`, `pixie_script`, `dreamer` for elegant or soft styles; `markerist`,
`biro_sloppy`, `doodle` for a handwritten feel; `pixel_game`, `bytebit` for retro gaming. Voice
clean-up for talking heads: audio effects `voice_focus`, `voice_crisp`, `podcast`.

Background removal (`"remove_bg": true`, CapCut's Auto removal) cuts the person or main subject out
of a clip. Use it when the new background has a job to do, not on every shot:

- **Subject pop**: the shot on the main track with the `blur` effect and/or saturation keyframes at
  -1 (two points, start and end), and the same file as an overlay with `"remove_bg": true`, `"at":
  "@shot"`, `"end": "@shot.end"`, the same `in` and `fit`, and `"mute": true`. The person stays sharp
  and in color while the background blurs or goes grey.
- **New background**: the background (B-roll, a still, a branded color card) on the main track, and
  the person as an overlay with `remove_bg`. For example, a talking head over the thing they are
  talking about.

It works best with one clear subject that stands out from the background. Hair, motion blur and
busy backgrounds give rough edges, so name those shots as things to check at handover.

## Text and captions

- Readable at phone size in 0.5 s: 2-6 words per line, max 2 lines, heavy weight, white or bright
  color with a black stroke (width 30-50) or shadow. Never thin text over busy footage.
- On screen long enough to read twice: ~0.3 s per word, minimum 1 s for titles.
- One title style, one caption style. Define them in `styles` and reuse them.
- Keep text in the safe zone (see `edit-spec.md`). Captions lower-middle, titles upper-middle.
- Do not cover faces or the product - check where the subject is in the contact sheet and move text.
- Language: write text in the language the user wrote in, unless they say otherwise. Check the font
  supports it (many decorative fonts are Latin-only).
- Fonts: `scripts/fonts.json` lists 50 free fonts picked by looking at every free font rendered in
  CapCut, each with its role (headline, body, script), moods and width. Pick from it by mood, pair one
  headline font with one body font, and use script fonts only for one or two accent words. Wide
  fonts (`bungee`, `resolve`, `marvin`, `brown_volky`, `marker`) need short lines. The looks in
  `scripts/looks.json` are tested pairings; start from one.

## Sound

- Music under speech: 0.1-0.25 or `duck`. Music alone: 0.5-0.8 (normalize by ear in CapCut).
- Always fade music: in 0.1-0.5 s (or start on a downbeat with no fade), out 0.8-2 s.
- Start the song where it is good; the intro of most songs is too slow for short-form.
- Mute or lower (0.2-0.4) natural sound on B-roll unless it adds something (waves, crowd cheer).
- Sound effects make cuts and text feel deliberate. Use the generated kit (`"sfx"`, see
  `edit-spec.md`) or the user's files; CapCut's own sound library is not in the catalog. Each sound
  lands with its peak one frame after its picture and a few dB over the music.
  - `whoosh` on a transition that moves (whip, slide, zoom, glitch), not on a dissolve or every hard
    cut. `pop` when a title or label appears, `tick` for counters, list items and small UI changes,
    `hit` on the one slam or drop that matters, `riser` (2 s) into a reveal, ending on a `hit`.
  - Restraint, as with transitions: three to six sounds in a 30 s reel. A sound on every cut and every
    word is as cheap as an effect on every clip. Not under talking-head speech except at its edges.
  - With `music.py`, put hits on the `drop` and `end_hit` times and risers into them; the track
    already has its own risers and booms there, so `gain: -4` keeps them from doubling up.
  - Leave the level to the default; adjust a single sound with `gain` in dB.

## Reframing between aspect ratios

- Horizontal footage on a vertical canvas: `"fit": "cover"` crops to the middle third. Check in the
  contact sheet where the subject is and shift with `transform.x` (positive = moves the frame right,
  revealing more of the left side; 16:9 footage covering 9:16 allows about -2.1..2.1, the sides).
  A subject that crosses the frame (someone walking, a bird, a car passing) leaves a fixed crop:
  follow it with `transform.x_path` (`scan_footage.py` gives it as `reframe_path`).
- When the whole frame matters (landscapes, group shots, text in frame): `"fit": "contain"` +
  `"background": "blur"`.
- Vertical footage on a horizontal canvas: `contain` + blur background, or two vertical clips side by
  side as overlays (`transform.scale` ~1, `x` = -0.5 and 0.5).

## Cheap-looking mistakes to avoid

- A different transition between every clip, or long (1 s+) flashy transitions everywhere.
- Effects stacked on effects, or a strong filter at 100 % that wrecks skin tones.
- Text that is too small, too long, low-contrast, or sits on top of the subject's face.
- Slow fade-in from black at the start of short-form content.
- Music that starts at the song's quiet intro or cuts off abruptly at the end.
- Slow motion on 24/30 fps footage (it stutters) - only slow down 50/60 fps sources.
- Black bars from a wrong `fit`, or the subject cropped out by `cover`.
- Clips held long after the action ended.
- Captions that drift out of sync: inline `words` or cues without a `source` are timeline times, so
  they do not follow your cuts. Caption from the transcript (or give `source`) instead.
- A cut that clips the first or last syllable of a word: keep ~0.1 s around the word times.

## Self-review before building

Read the `--check` timeline and ask:

1. Does the first second earn the next ten? What does the viewer see at 0.0 s?
2. Is every shot's length justified, and does pacing vary?
3. Do cuts land on beats/motion where intended (compare timeline times with the beat list)?
4. Is there exactly one look, one title style, one caption style?
5. Is all text readable, in the safe zone, off the faces, and on screen long enough?
6. Does anything run past the main track end? Does the music end cleanly?
7. Are only free resources used (unless the user has Pro)?

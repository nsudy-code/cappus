# Recipes: a finished, good-looking edit from a one-line request

Most people ask for very little ("make a promo for my website", "turn these photos into a reel") and
judge the first result. These recipes turn that kind of request into a complete edit with no
follow-up questions: they decide the structure, the look, the music and every timing, so the first
draft already looks designed. State the choices you made in one line; do not ask about them first.

## Contents

- [Always: look, music, motion](#always-look-music-motion)
- [Website to promo video](#website-to-promo-video)
- [Photos or clips to a beat-synced reel](#photos-or-clips-to-a-beat-synced-reel)
- [Writing on-screen text that works](#writing-on-screen-text-that-works)
- [Before you hand over](#before-you-hand-over)

## Always: look, music, motion

1. **Let `looks.py suggest` pick the look** (`--theme` with the user's words, `--scan` / `--site`
   when there is footage or a site, `--record`). It matches the business and the footage, takes the
   accent color from the brand, the site or the footage, and rotates between tested font pairings so
   two edits in a row never look alike. The table below is what it is based on:

   | the business | look |
   |---|---|
   | software, websites, agencies, apps, consultants, courses | `clean_tech` |
   | sales, launches, gyms, events, restaurants with offers | `bold_promo` |
   | travel, property, hotels, documentaries, brand stories | `cinematic` |
   | kids, cafes, desserts, pets, fun products | `playful` |
   | fashion, jewelry, beauty clinics, salons, premium services | `luxury` |
   | sport, streetwear, gaming, cars, music | `street` |

   In the spec: the `spec` part of the suggestion, for example `"look": "cinematic", "fonts":
   {"headline": "bebas", "body": "kilig"}, "brand": {"accent": "#61CCFF"}`. Texts then use
   `"style": "title" | "accent" | "big" | "label"`, and captions get the look's caption style.
2. **Music on a known grid.** Use the user's track when they give one (and `probe.py --beats`). With
   none, generate one: `python <skill>/scripts/music.py media/music.wav --mood <look's mood>
   --bpm <look's bpm> --length 30 --drop <s> --breath <s> --end-hit <s>`. Its `.beats.json` holds
   the exact beat times; build every cut and text change from it. Tell the user the music is a
   generated placeholder that is free to use, and that a CapCut library track at the same BPM keeps
   the sync if its first downbeat sits at 0 and its drop at the same time.
3. **Motion from presets, not raw keyframes.** `"enter"` / `"exit"` on overlays and texts give eased
   movement that ends exactly on the item's resting place (see `edit-spec.md`). The look's styles
   already carry the text entrance; give cards the look's `cards.enter`, and a slow drift
   (`keyframes.scale` from the card scale to `scale * (1 + cards.drift)` over the card's length).

## Kinetic typography (the default for a promo with no footage)

The most striking result from nothing but words and music, and what people react to most. Use it for
a website, a service, a launch or an announcement whenever there is no footage that sells by itself.
Look `kinetic`. It is built from these rules, each one taken from an edit that worked:

1. **The script first, as a beat list.** Write the message as short phrases from the source (the
   site's headline, what it offers, proof, price, call to action), then break it into one or two
   words per beat. Small connecting words ("but", "with", "for you", "bikin", "tapi...") are the
   `soft` style; the words that carry the meaning are `word` / `tilt` / `accent`. Alternating the
   two is what gives the rhythm: HEAVY CAPS, soft italic, HEAVY CAPS.
2. **On the grid.** A real track: `probe.py --beats`, and check the beat by ear-math (a 92 BPM track
   has a 0.652 s beat). A generated one: its `.beats.json`. Main words start on beats; the second
   word of a pair on the half beat; single giant letters (`letter` style, one per corner or in a row:
   "S T O P", "L U X") on quarter beats; echo copies 1/8 beat apart.
3. **Size fills the frame.** `word` styles use `fit_width` (0.86 of the canvas), so a short word is
   huge and a long one still fits; the builder computes the size from the font. Two-line phrases
   ("LANDING\nPAGE") are sized by their longest line. Never leave a lone word small in the middle.
4. **Every word moves twice: in, then breathing.** An entrance from the kinetic set (`slam`,
   `slam_tilt`, `whip_left` / `whip_right`, `fall` / `jump`, `spin`) and a `drift` (scale 1.0 ->
   1.05 over its life, in the look). Rotate a few words by 6-9 degrees (`rotation`), alternating
   sides. Vary entrances by meaning: whips for lists, falls for facts, spin for one surprise,
   slam for the punchline.
5. **Stack the key word.** `"echo": {"count": 4, "spacing": 0.2, "stagger": 0.08}` on the one or
   two most important words repeats them above and below as outlines, each 1/8 beat later.
   The copies land `spacing` x 1, x 2 ... above and below the word, so keep any other text on
   screen at the same time further away than the outermost copy (or give the word no echo).
6. **End sections by flying through.** `"exit": "zoom_through"` on the last word before a new
   section (and before the end card): the camera seems to fly through the letters into what comes
   next. No CapCut transitions at all.
7. **Hits, sparingly.** `shake` (0.25 s) on 4-6 accent beats: the drop, the key claim, the price, the
   brand. Nothing else shakes.
8. **The end card holds.** The brand or domain (`big`), one soft line under it, the action
   (`title`, small), all on screen for the last 2-3 s with only the drift moving.

A 26-30 s edit has about 50 text items. Write them with a small script (a list of
`(beat, text, style, extra)` rows turned into spec items) rather than by hand, so retiming means
changing the grid, not 50 numbers.

## Website to promo video

The request: "make a promo for my website" plus a URL. Nothing else is needed. Make it as
**kinetic typography** (above) by default, with the words from `site.json`. Use the phone-card
version below when the site's own visuals sell it (a portfolio, products, an app screen); a mix
works too: kinetic text with two or three cards for the proof section.

1. **Capture the site** (needs Playwright, see Setup):
   `python <skill>/scripts/site_capture.py <url> media/site --dark` (drop `--dark` for a light site;
   open the English page, such as `/en/`, when the video is in English). Read `media/site/sheet.jpg`
   and `media/site/site.json`. Pick 7-10 shots: the hero, what they offer, proof (portfolio, clients,
   numbers), how it works, the price or offer, and contact. Skip shots that are mostly empty space
   or cut a section in half.
2. **Write the script from `site.json` only**: headings, buttons, prices and contact details. Never
   invent a claim, a number or a client. Translate faithfully when the site is in another language.
3. **Background**: a dark animated gradient in the site's own background color (ffmpeg
   `gradients` source with `c0` = `colors.background`) for dark sites; a light one for light sites.
4. **Cards**: each shot as an overlay "phone card": `"transform": {"scale": 0.72, "y": -0.22}`,
   `"mask": {"type": "rectangle", "size": 1.0, "width": 1.0, "round": 8}`, the look's card enter,
   and a slow drift. **The first card has no enter**: the frame at 0.0 s must already show the hook
   in full (a card that rises or fades in leaves the first frame empty). Quick proof swaps on beats
   are hard cuts too. Text sits above the card on two lines: `y = 0.72` (title) and `y = 0.60`
   (accent); the card's top edge is at `y = 0.50`. On the end card put the action line at `y = 0.58`
   or higher, because the drift brings the card closer to it.
5. **Beat sheet** for 30 s at the generated track's BPM (scale the times to the grid; at 120 BPM a
   beat is 0.5 s and a bar 2 s):

   | time | section | cards | text |
   |---|---|---|---|
   | 0 - drop (2 bars) | hook | the hero | the problem or the promise in 2 lines, one line per 2 beats |
   | drop - +3 bars | what they do | one card per bar | title holds ("I BUILD"), the accent line changes every 1-2 beats |
   | +2.5 bars | proof | portfolio / clients, swaps on beats | "REAL CLIENTS." / "LIVE TODAY." then one name per card |
   | breath bar | breath | none | one big line alone ("FIVE STEPS.") while the riser builds |
   | 2 bars | how it works | the process | one step per beat |
   | 2 bars | offer | price, guarantees | the price, then what the buyer owns or gets |
   | end hit - end | call to action | contact | the domain big, the action ("CHAT ON WHATSAPP") smaller |

   One hit effect (the look's `hit`) on the drop and one on the end hit; nothing else shakes.
6. **Self-check** the `--check` timeline against the beat map (every `at` on a beat), fix every
   fit warning, then build.

## A pile of footage into one edit

The request: "make these clips into one video" with a folder of phone clips. The user cannot say
what good looks like, so every decision below is yours. Do not ask which clips to use.

1. **Sort it like an editor**: `python <skill>/scripts/scan_footage.py <folder> --out <scratch>/scan`
   splits every file into shots and scores each 0-100 for sharpness, exposure, shake and motion,
   finds each shot's best window (`best.in` / `best.out`) and peak, drops duplicates (the same
   footage twice: copies, re-exports, edited versions), marks `similar_to` (the same scene twice),
   and proposes `adjust` (color matching) and `reframe_x` (where the subject is, for a vertical
   crop), plus `reframe_path` when the subject moves across the frame in the best window (a walker,
   a bird, a car) and a fixed crop would lose it. **Read `best.jpg`** before deciding: the score is technical, you are the art director. A
   silhouette, a dusk window or a deliberately soft shot can score low and still be the most
   beautiful frame; a sharp, well-exposed shot of nothing is still nothing.
2. **Name the story from what you see** and pick its structure:

   | footage | structure (in order) |
   |---|---|
   | trip / holiday | the most stunning wide shot, getting there (plane, road), arrival (aerials, first view), doing things (people, details), the golden hour, the night, the best people shot last |
   | event / wedding / party | the venue, people arriving, the key moment (speech, cake, stage) at the drop, the crowd, details, the send-off |
   | product / shop / food | the hero shot, the problem or the craving, details close up, it in use, the price or how to get it |
   | day in the life / vlog | morning, getting ready, the work or the outing, a pause, the evening, a closing line |
   | sport / action | the biggest move first (as the hook), the build-up, a burst of action shots on the drop, the result |

   Without people the structure is the same with places. Never more than one shot per `similar_to`
   group back to back.
3. **Choose shots, not files.** 8-14 shots for 20-30 s. Use each shot's best window, trimmed to the
   beat grid. The hook is the single best-looking shot (often not the first file); the second best
   shot ends the edit. Skip shots under score 50 unless you saw in `best.jpg` that they are good.
4. **Energy follows the music.** Calm, wide, slow shots in the intro; shots with the most `motion`
   and the people on the drop; a slower hero shot to end. A clip with `fps` 50 or more may play at
   `speed` 0.5 for one big moment; never slow down 24-30 fps footage.
5. **Make it look like one video.** Put each shot's `adjust` in the clip (`"adjust": {"brightness":
   -0.1}`) so the shots match, then one look over everything: the look's filter on a `filters` track
   across the whole edit at 40-60. Night and golden-hour shots stay as they are; that light is the
   mood.
6. **Reframe properly.** Horizontal footage on a vertical canvas: `"fit": "cover"` with
   `"transform": {"x": <reframe_x>}`, plus a slow `motion` (`push_in`, or a pan in the direction the
   action moves). A shot with `reframe_path` follows its subject instead: `"transform": {"x_path":
   <reframe_path>}` (copy it as is; its times are source seconds, so it fits any in/out inside the
   best window) with `push_in` or no motion, never a pan (both move `x`). Vertical footage on a vertical canvas just uses `cover`. A wide shot with two
   people or a group loses someone in a vertical crop: use `"fit": "contain"` with
   `"background": "blur"` for it, or skip it.
7. **Words on footage.** A title on the hook and a closing line, in the look's styles and the
   font pairing from `looks.py suggest` (for footage it usually picks `cinematic`: a huge condensed
   headline in white over a small label; the fonts vary between edits). No heavy drop shadow: a
   big shadow looks cheap. Legibility comes from placement: put text at the shot's `text_y` (the
   calmest, darkest band), never over a bright sky, fireworks or a face. Kinetic words fit footage too: a few
   `slam` words on the drop over the action, not a word on every beat. Captions only when someone
   speaks.
8. **Transitions**: hard cuts on beats; one transition from the look's family where time or place
   changes (arrival, sunset to night).

## Photos or clips to a beat-synced reel

1. `probe.py` every file, contact sheets for clips, `--beats` on the user's music (or generate it).
2. Order: strongest image first, then build energy, second-best last. Remove near-duplicates.
3. Lengths on the grid: 1 bar per photo in the intro, 2 beats after the drop, 1 beat in a burst
   before the end; hero shots hold a full bar.
4. Every still gets motion, alternating `push_in`, `pull_out`, `pan_left`, `pan_right`; clips get
   `"fit": "cover"` and an `in` just before the action.
5. Text only where it adds something: a title on the hook, a place or date, a closing line. Use the
   look's `title` / `big` styles; at most 3-5 words on screen at a time.
6. Hard cuts on beats; one transition from the look's family at the drop and one before the end.

## Color that reads (and does not repeat the background)

- The footage's most common color is its background (sea, sky, leaves): never use it for text. The
  accent `scan_footage.py` reports is the strongest color far from it (the sunset's orange in beach
  footage), and `looks.py suggest` passes it on.
- One accent, on one or two key words per section; everything else white (or dark on bright
  backgrounds). The looks' color lists already fall back to white or dark where the accent would wash
  out, and the builder checks every text against the frame behind it.
- Dark text only over truly bright areas (sand, snow, sky, a white wall); night, sunset and busy
  shots get white. A title and its label share the same tone.
- Fix a contrast warning by moving the text to the shot's `text_y`, not by adding a shadow or an
  outline (both look cheap on footage). Where the footage is busy anyway, the builder dims the band
  behind the text with a soft gradient on its own.

## Writing on-screen text that works

- **Short lines.** At most about 16 characters per line at the look's sizes; the builder warns
  when a line will wrap. Split a phrase across the two text lines instead of shrinking it.
- **Change on the beat.** A new line starts exactly on a beat, and lines that belong together enter
  one beat apart (title first, accent one beat later).
- **Capitals for headlines, sentence case for labels.** Numbers and prices go in the accent style.
- **End on the action**, with the domain or handle exactly as written on the site.

## Before you hand over

If you can see the user's screen (computer use), look at the draft yourself before handing over,
as described in `capcut-notes.md` ("Looking at a draft in CapCut"): check that no line wraps or
overlaps a card, that text sits inside the safe zone, and that the hook frame (0.0 s) looks good.

Then hand over in plain words, not a technical report:

> Your video is ready in CapCut: open the project "**<name>**" and press Play. It is 30 seconds,
> made from your website, with music that is free to use.
> Three things you can change in one click: the music (Audio > Music, any track around 120 BPM),
> any text (double-click it), and the colors (select a text > Style).

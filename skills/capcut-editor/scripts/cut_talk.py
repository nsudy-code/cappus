#!/usr/bin/env python3
"""Cut a talking-head recording into a jump-cut edit spec: dead air, fillers and flubbed takes out,
punch-ins that alternate with the cuts, the strongest lines ranked as hooks, and slots for B-roll.

  cut_talk.py talk.mp4                        # needs talk.transcript.json beside it (transcribe.py)
  cut_talk.py talk.mp4 --out edit.json        # where to write the spec (default talk.cut.json)
  cut_talk.py talk.mp4 --hook-first           # open on the best line as a teaser, then the whole talk
  cut_talk.py talk.mp4 --broll a.mp4 b.mp4    # put these clips in the B-roll slots (muted, full frame)
  cut_talk.py talk.mp4 --max-pause 0.25 --punch 1.2 --look clean_tech
  cut_talk.py long.mp4 --from 312.4 --to 351.0   # only this part of the recording (shorts.py uses it)

Writes an edit spec for build_draft.py and prints a JSON report: what was cut and why (with the
words), clip lengths, hook candidates with their scores, and the B-roll slots with what is said
there. Read the report, look at anything cut as a retake, then treat the spec like any other:
reorder, drop a clip, add a title on "@hook", fill the B-roll slots with footage that shows what
is said, and build it.

Times named `start`/`end`/`from`/`to` are seconds in the source file; `at` is timeline seconds.
The silence check needs ffmpeg (--no-silence skips it).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Hesitation sounds, in the spellings Whisper uses for English and Indonesian. An all-caps word is an
# acronym ("ER", "EM"), never a filler.
FILLER = re.compile(r"^(?:u+[hm]+|e+[hm]*|e+r+m*|h+m+|m{2,}|m+h+m+|a+h+|anu)$")
SENTENCE_END = ".?!…"
PHRASE_END = SENTENCE_END + ",;:"

# Words that make a line worth opening on: contradiction, warning, secret, number, question.
HOOK_WORDS = {
    # Indonesian
    "ternyata": 2, "padahal": 1.5, "jangan": 1.5, "bahaya": 2, "berbahaya": 2, "mitos": 2, "fakta": 1.5,
    "rahasia": 2, "salah": 1.5, "kesalahan": 2, "keliru": 1.5, "kenapa": 1.5, "mengapa": 1.5,
    "gimana": 1, "bagaimana": 1, "awas": 2, "hindari": 1.5, "stop": 1.5, "berhenti": 1.5,
    "sebenarnya": 1.5, "sebenernya": 1.5, "justru": 1.5, "jarang": 1, "kebanyakan": 1.5,
    "terbukti": 1.5, "penelitian": 1, "riset": 1, "meninggal": 1.5, "kematian": 1.5, "rusak": 1,
    "diam-diam": 1.5, "penting": 1, "wajib": 1, "rugi": 1, "gratis": 1, "nggak": 0.3, "gak": 0.3,
    "tidak": 0.3, "bukan": 0.5, "semua": 0.5, "selalu": 0.5, "cuma": 0.5, "hanya": 0.5,
    # English
    "actually": 1.5, "never": 1, "mistake": 2, "mistakes": 2, "secret": 2, "wrong": 1.5, "myth": 2,
    "truth": 1.5, "why": 1.5, "how": 1, "dangerous": 2, "nobody": 1.5, "everyone": 1, "most": 1,
    "worst": 1.5, "best": 1, "proven": 1.5, "research": 1, "study": 1, "don't": 1.5, "stop": 1.5,
    "only": 0.5, "always": 0.5, "but": 0.3, "free": 1,
}
NUMBER_WORDS = {"satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan", "sepuluh",
                "seratus", "ribu", "juta", "persen", "one", "two", "three", "four", "five", "six", "seven",
                "eight", "nine", "ten", "hundred", "thousand", "million", "percent", "first", "pertama"}
YOU_WORDS = {"kamu", "anda", "kalian", "lo", "lu", "you", "your", "you're"}
GREETING = {"halo", "hai", "hello", "hi", "hey", "assalamualaikum", "assalamu'alaikum", "selamat", "welcome",
            "guys", "teman-teman", "temen-temen", "gaes"}
STOPWORDS = {
    "yang", "dan", "di", "ke", "dari", "ini", "itu", "aku", "saya", "kamu", "kita", "kami", "dia", "ada",
    "untuk", "dengan", "juga", "jadi", "kalau", "kalo", "karena", "tapi", "atau", "sudah", "udah", "akan",
    "bisa", "lagi", "aja", "saja", "ya", "nah", "terus", "pada", "dalam", "oleh", "seperti", "kayak",
    "banget", "sangat", "lebih", "biar", "agar", "supaya", "nya", "punya", "begitu", "gitu", "gini",
    "adalah", "orang", "hal", "tahu", "tau", "mau", "sih", "dong", "deh", "kan", "loh", "lah", "pun",
    "para", "sama", "bagi", "kalian", "mereka", "setelah", "sebelum", "masih", "belum", "tidak", "nggak",
    "gak", "enggak", "bukan", "apa", "siapa", "kapan", "sekarang", "nanti", "memang", "emang", "harus",
    "about", "people", "thing", "things", "know", "think", "more", "some", "because", "would", "could",
    "also", "been", "into", "than", "them", "their", "these", "those", "will", "make", "makes", "much",
    "many", "only", "which", "where", "while", "should", "means", "going", "want", "need", "first",
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with", "is", "are", "was",
    "were", "be", "it", "this", "that", "you", "your", "i", "we", "they", "he", "she", "so", "just",
    "like", "really", "very", "then", "there", "here", "have", "has", "do", "does", "what", "when",
}


def norm(word: str) -> str:
    return re.sub(r"^[^\w'-]+|[^\w'-]+$", "", word.lower())


def is_filler(word: str) -> bool:
    bare = re.sub(r"^\W+|\W+$", "", word)
    if len(bare) >= 2 and bare.isupper():
        return False
    return bool(FILLER.match(bare.lower()))


def rel(path: Path, base: Path) -> str:
    """Relative to the spec when the file is beside it or one folder up, else absolute."""
    try:
        r = Path(os.path.relpath(path, base))
    except ValueError:  # another drive on Windows
        return path.as_posix()
    return r.as_posix() if r.parts.count("..") <= 1 else path.as_posix()


# ---------------------------------------------------------------------------------------- removals

def phrases_of(words, idx, gap):
    """Split word indexes into phrases at punctuation and pauses longer than `gap`."""
    out, cur = [], []
    for i in idx:
        if cur and (words[i]["start"] - words[cur[-1]]["end"] > gap
                    or words[cur[-1]]["word"][-1:] in PHRASE_END):
            out.append(cur)
            cur = []
        cur.append(i)
    if cur:
        out.append(cur)
    return out


def mark_retakes(words, drop, gap=0.3, window=8.0):
    """A phrase that the next phrase (or the one after a short aside) starts over: keep the last take."""
    alive = [i for i in range(len(words)) if i not in drop]
    ph = phrases_of(words, alive, gap)
    toks = [[norm(words[i]["word"]) for i in p] for p in ph]
    for a in range(len(ph)):
        if ph[a][0] in drop:
            continue
        between = 0
        for b in range(a + 1, min(a + 4, len(ph))):
            if words[ph[b][0]]["start"] - words[ph[a][-1]]["end"] > window:
                break
            p, q = toks[a], toks[b]
            k = 0
            while k < min(len(p), len(q)) and p[k] == q[k]:
                k += 1
            same = len(p) >= 4 and len(set(p) & set(q)) >= 0.7 * max(len(set(p)), len(set(q)))
            if (k >= 2 and k >= min(3, len(p))) or same:
                kept = " ".join(words[i]["word"] for i in ph[b])
                for c in range(a, b):
                    for i in ph[c]:
                        drop[i] = ("retake", kept)
                break
            between += len(ph[b])
            if between > 6:
                break
    # a stutter inside a phrase: "saya mau saya mau ke" -> drop the first copy
    alive = [i for i in range(len(words)) if i not in drop]
    t = [norm(words[i]["word"]) for i in alive]
    for n in (4, 3, 2):
        for s in range(len(t) - 2 * n + 1):
            close = words[alive[s + n]]["start"] - words[alive[s + n - 1]]["end"] <= 1.0
            if close and t[s:s + n] == t[s + n:s + 2 * n] and all(alive[s + j] not in drop for j in range(2 * n)):
                kept = " ".join(words[alive[s + n + j]]["word"] for j in range(n))
                for j in range(n):
                    drop[alive[s + j]] = ("repeat", kept)


def subtract(segs, cuts):
    """Interval difference: segs minus cuts (both lists of [a, b])."""
    out = []
    for a, b in segs:
        pieces = [[a, b]]
        for c, d in cuts:
            nxt = []
            for x, y in pieces:
                if d <= x or c >= y:
                    nxt.append([x, y])
                    continue
                if c > x:
                    nxt.append([x, c])
                if d < y:
                    nxt.append([d, y])
            pieces = nxt
        out += pieces
    return out


def plan_clips(words, drop, duration, pad, max_pause, silences):
    """Kept words -> [[in, out]] source ranges, with the reason for every gap that was cut."""
    runs, cur = [], []
    for i, w in enumerate(words):
        if i in drop:
            if cur:
                runs.append(cur)
            cur = []
            continue
        if cur and w["start"] - words[cur[-1]]["end"] > max_pause:
            runs.append(cur)
            cur = []
        cur.append(i)
    if cur:
        runs.append(cur)

    segs = []
    for r in runs:
        first, last = r[0], r[-1]
        a, b = words[first]["start"] - pad, words[last]["end"] + pad
        if first > 0:  # never reach back into a dropped word, nor past the middle of a pause
            prev = words[first - 1]
            a = max(a, prev["end"] if (first - 1) in drop else (prev["end"] + words[first]["start"]) / 2)
        if last + 1 < len(words):
            nxt = words[last + 1]
            b = min(b, nxt["start"] if (last + 1) in drop else (words[last]["end"] + nxt["start"]) / 2)
        segs.append([max(0.0, a), min(duration, b) if duration else b])

    # Whisper stretches a word over the silence after it; cut silences the words hide, keeping `pad`.
    cuts = [[s + pad, e - pad] for s, e in silences if e - s > max_pause and e - s > 2 * pad]
    segs = subtract(segs, cuts)
    if cuts:
        # A short burst of sound between two silences that holds no word, or only a one- or two-letter
        # one, is a hesitation Whisper wrote down as "a" / "e" or left out: "is that, uh, coffee".
        kept = [w for i, w in enumerate(words) if i not in drop]

        def lone_sound(a, b):
            if b - a >= 0.6 or (a > 0 and not any(abs(c[1] - a) < 1e-6 for c in cuts)) \
                    or not any(abs(c[0] - b) < 1e-6 for c in cuts):
                return False
            inside = [w for w in kept if a <= (w["start"] + w["end"]) / 2 < b]
            return all(len(norm(w["word"])) <= 2 and not re.search(r"\d", w["word"]) for w in inside)

        lone = [s for s in segs if lone_sound(*s)]
        segs = [s for s in segs if not lone_sound(*s)]
    else:
        lone = []

    merged = []
    for s in segs:
        if merged and s[0] - merged[-1][1] < 0.05 and not any(
                merged[-1][1] <= (words[i]["start"] + words[i]["end"]) / 2 < s[0] for i in drop):
            merged[-1][1] = s[1]
        else:
            merged.append(list(s))
    return [[round(a, 3), round(b, 3)] for a, b in merged if b - a > 0.05], lone


def snap_words(words, drop, ranges, lone):
    """Kept words with their times moved into the clip that plays them.

    Whisper's word times drift by a few tenths of a second around pauses, so a word whose sound is in a
    clip can have its middle in the silence just cut, and the builder (which places a word by its middle)
    would leave it out of the captions. Each word goes to the kept range it overlaps most; a word that
    overlaps a dropped hesitation more is left out, and so is one with no range within 0.5 s."""
    out = []
    keep = [(a, b, True) for a, b in ranges] + [(a, b, False) for a, b in lone]
    for i, w in enumerate(words):
        if i in drop:
            continue
        s, e = w["start"], w["end"]
        best = max(keep, key=lambda r: min(e, r[1]) - max(s, r[0]), default=None)
        if best is None:
            continue
        a, b, ok = best
        overlap = min(e, b) - max(s, a)
        if overlap <= 0:
            near = min(ranges, key=lambda r: min(abs(r[0] - e), abs(s - r[1])))
            if min(abs(near[0] - e), abs(s - near[1])) > 0.5:
                continue
            a, b, ok = near[0], near[1], True
        if not ok:
            continue
        s2, e2 = max(s, a), min(e, b)
        if e2 - s2 < 0.08:  # squeezed against a clip edge: give it a sliver inside the clip
            if s2 >= b - 0.08:
                s2, e2 = max(a, b - 0.15), b
            else:
                s2, e2 = a, min(b, a + 0.15)
        out.append(dict(w, start=round(s2, 3), end=round(e2, 3)))
    return out


def describe_gaps(clips, words, drop, duration, lone=()):
    """What each removed stretch was, for the report."""
    removed, cursor = [], 0.0
    bounds = [(c[0], c[1]) for c in clips] + [(duration, duration)]
    for a, b in bounds:
        if a - cursor > 0.05:
            # words said in the cut part: dropped ones, and any Whisper places wholly inside it
            inside = [i for i, w in enumerate(words)
                      if (i in drop and cursor <= (w["start"] + w["end"]) / 2 < a)
                      or (cursor <= w["start"] and w["end"] <= a)]
            why = "pause"
            reasons = {drop[i][0] for i in inside if i in drop}
            if "retake" in reasons:
                why = "retake"
            elif "repeat" in reasons:
                why = "repeat"
            elif "filler" in reasons or inside or any(cursor <= x and y <= a for x, y in lone):
                why = "filler"
            item = {"from": round(cursor, 2), "to": round(a, 2), "why": why}
            if inside:
                item["text"] = " ".join(words[i]["word"] for i in inside)
            kept = next((drop[i][1] for i in inside if i in drop and drop[i][1]), None)
            if kept:
                item["kept_take"] = kept
            removed.append(item)
        cursor = max(cursor, b)
    return removed


# ------------------------------------------------------------------------------------- hooks, B-roll

def sentences_of(words, drop, gap=0.8):
    alive = [i for i in range(len(words)) if i not in drop]
    out, cur = [], []
    for i in alive:
        if cur and (words[i]["start"] - words[cur[-1]]["end"] > gap
                    or words[cur[-1]]["word"][-1:] in SENTENCE_END):
            out.append(cur)
            cur = []
        cur.append(i)
    if cur:
        out.append(cur)
    return out


def score_hook(ws):
    toks = [norm(w["word"]) for w in ws]
    text = " ".join(w["word"] for w in ws)
    dur = ws[-1]["end"] - ws[0]["start"]
    score, why = 0.0, []
    hits = sorted({t for t in toks if t in HOOK_WORDS}, key=lambda t: -HOOK_WORDS[t])
    if hits:
        score += min(4.0, sum(HOOK_WORDS[t] for t in hits))
        why.append("says " + ", ".join(hits[:4]))
    if any(re.search(r"\d", t) for t in toks) or any(t in NUMBER_WORDS for t in toks) or "%" in text:
        score += 1.5
        why.append("a number")
    if text.rstrip()[-1:] == "?":
        score += 1.0
        why.append("a question")
    if any(t in YOU_WORDS for t in toks):
        score += 0.5
        why.append("talks to the viewer")
    if 1.5 <= dur <= 8:
        score += 1.0
        why.append(f"{dur:.1f} s, a good hook length")
    elif dur > 12 or dur < 1.5:
        score -= 1.0
        why.append(f"{dur:.1f} s, {'long' if dur > 12 else 'short'} for a hook")
    if toks and toks[0] in GREETING:
        score -= 3.0
        why.append("a greeting")
    conf = sum(w.get("p", 1) for w in ws) / len(ws)
    if conf < 0.6:
        score -= 1.0
        why.append("low transcription confidence")
    return round(score, 2), why


def content_words(ws, n=3):
    toks = [norm(w["word"]) for w in ws]
    cand = [t for t in toks if len(t) >= 4 and t not in STOPWORDS and not is_filler(t)]
    seen = []
    for t in sorted(cand, key=len, reverse=True):
        if t not in seen:
            seen.append(t)
    return seen[:n]


def keywords_of(words, sentences, every=1):
    """One word per sentence to color in the captions: a number ("90%", "3") when there is one, else
    the longest uncommon word (6+ letters, said in at most two sentences)."""
    said = {}
    for s in sentences:
        for t in {norm(words[i]["word"]) for i in s}:
            said[t] = said.get(t, 0) + 1
    out = []
    for n, s in enumerate(sentences):
        if n % every or len(s) < 3:
            continue
        toks = [re.sub(r"[^\w%]+", "", words[i]["word"].lower()) for i in s]
        nums = [t for t in toks if re.search(r"\d", t)]
        if nums:
            pick = max(nums, key=len)
        else:
            cand = [t for t in toks if len(t) >= 6 and t not in STOPWORDS and not is_filler(t)
                    and said.get(t, 0) <= 2]
            pick = max(cand, key=len) if cand else None
        if pick and pick not in out:
            out.append(pick)
    return out


def lower_third(name, role, at, look_styles, duration=3.5):
    """Texts for who is speaking, left-aligned above the captions: the name in a colored box, the
    role under it. Positions from the fonts' measured widths, so both boxes start at the same edge."""
    widths = json.loads((Path(__file__).resolve().parent / "fonts.json").read_text(encoding="utf-8"))["fonts"]
    fallback = {"name": {"font": "poppins_bold", "size": 8, "bold": True, "color": "#111111",
                         "background": {"color": "#FFD400", "opacity": 1, "radius": 0.2}},
                "role": {"font": "poppins_bold", "size": 6, "color": "#FFFFFF",
                         "background": {"color": "#000000", "opacity": 0.6, "radius": 0.2}}}
    out = []
    for key, text, y in (("name", name, -0.3), ("role", role, -0.39)):
        if not text:
            continue
        st = look_styles.get(key) or fallback[key]
        wf = float(widths.get(st.get("font", "poppins_bold"), {}).get("width", 2.6))
        half = 2 * len(text) * wf * float(st.get("size", 8)) / 1080 + 0.06  # + the box's padding
        item = {"text": text, "at": round(at + (0.15 if key == "role" else 0), 2), "duration": duration,
                "y": y, "x": round(-0.86 + half / 2, 3), "track": "lower_third", "note": "lower third"}
        if key in look_styles:
            item["style"] = key
        else:
            item.update(fallback[key])
        out.append(item)
    return out


def to_timeline(clips, t):
    """Source second -> timeline second, through the clip that plays it (or None)."""
    at = 0.0
    for c in clips:
        if c["in"] <= t < c["out"]:
            return at + t - c["in"]
        at += c["out"] - c["in"]
    return None


def broll_slots(clips, words, sentences, total, every, length, skip):
    slots, last = [], -1e9
    for s in sentences:
        ws = [words[i] for i in s]
        if s[0] in skip:
            continue
        cw = content_words(ws)
        if not cw:
            continue
        anchor = next(w for w in ws if norm(w["word"]) == cw[0])  # the most specific word: show that
        at = to_timeline(clips, (anchor["start"] + anchor["end"]) / 2)
        if at is None:
            continue
        at = max(0.0, at - (anchor["end"] - anchor["start"]) / 2)
        end_src = to_timeline(clips, ws[-1]["end"] - 0.01)
        room = (end_src if end_src is not None else at + length) - at
        dur = min(length, max(1.2, room))
        if at < 3.0 or at + dur > total - 1.0 or at - last < every:
            continue
        slots.append({"at": round(at, 2), "duration": round(dur, 2),
                      "says": " ".join(w["word"] for w in ws), "keywords": cw})
        last = at
    return slots


# ------------------------------------------------------------------------------------------- main

def load_transcript(video: Path, given):
    path = Path(given) if given else video.with_suffix(".transcript.json")
    if not path.is_file():
        raise SystemExit(f"no transcript at {path}: run transcribe.py {video.name} first "
                         "(or pass --transcript)")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        words = [w for w in data["words"] if str(w.get("word", "")).strip()]
    except (OSError, ValueError, KeyError, TypeError):
        raise SystemExit(f"{path} is not a transcript made by transcribe.py")
    if not words:
        raise SystemExit(f"{path} has no words: is there speech in {video.name}?")
    return path, data, words


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="the talking-head recording")
    ap.add_argument("--transcript", help="default: <video>.transcript.json beside it")
    ap.add_argument("--from", dest="t_from", type=float, help="cut only from here (seconds in the source)")
    ap.add_argument("--to", dest="t_to", type=float, help="... to here")
    ap.add_argument("--out", help="spec to write (default: <video>.cut.json beside it)")
    ap.add_argument("--name", help="draft name (default: <video>-cut)")
    ap.add_argument("--look", help="a look from looks.py (edu, talk, ...): caption style, highlight, keywords")
    ap.add_argument("--speaker", help="lower third: who is speaking (\"dr. Aisya\")")
    ap.add_argument("--role", help="lower third: under the name (\"Dokter Umum\")")
    ap.add_argument("--no-keywords", action="store_true", help="don't color a keyword per sentence")
    ap.add_argument("--pad", type=float, default=0.12, help="seconds kept before/after speech (0.12)")
    ap.add_argument("--max-pause", type=float, default=0.35, help="a longer pause is cut (0.35 s)")
    ap.add_argument("--keep-fillers", action="store_true", help="leave um/eh/hmm in")
    ap.add_argument("--keep-retakes", action="store_true", help="leave restarted phrases in")
    ap.add_argument("--punch", type=float, default=1.18, help="punch-in scale, 1 = off (1.18)")
    ap.add_argument("--punch-hold", type=float, default=1.0,
                    help="change framing at a cut once the current one has run this long (1.0 s)")
    ap.add_argument("--face-y", type=float,
                    help="where the face is, as a fraction of the frame height from the top; skips face "
                         "detection (default: found by faces.py, else 0.38)")
    ap.add_argument("--no-faces", action="store_true", help="don't look for the face (OpenCV)")
    ap.add_argument("--loudness", type=float, default=-14.0,
                    help="level the speech (and any music) to this many LUFS (default -14, what TikTok/Reels play at)")
    ap.add_argument("--no-loudness", action="store_true", help="keep the recording's own level")
    ap.add_argument("--denoise", action="store_true",
                    help="switch on CapCut's Reduce noise on every clip (CapCut Pro): hum, fan, room noise")
    ap.add_argument("--fit", choices=["cover", "contain"], default="cover")
    ap.add_argument("--hooks", type=int, default=3, help="hook candidates to report (3)")
    ap.add_argument("--hook-first", action="store_true", help="open on the best hook line, then the talk")
    ap.add_argument("--hook-max", type=float, default=8.0, help="longest teaser (8 s)")
    ap.add_argument("--broll", nargs="*", default=[], help="footage for the B-roll slots, in order")
    ap.add_argument("--broll-every", type=float, default=6.0, help="seconds between B-roll slots (6), 0 = none")
    ap.add_argument("--broll-length", type=float, default=2.0, help="seconds per B-roll slot (2.0)")
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--no-silence", action="store_true", help="skip the ffmpeg silence check")
    ap.add_argument("--noise-db", type=float, default=-35.0, help="silence threshold (-35 dB)")
    ap.add_argument("--preset", help="a series preset (presets.py): look, colors, captions, speaker, cut settings")
    pre, _ = ap.parse_known_args()
    preset = {}
    if pre.preset:  # the preset's settings become the defaults; flags given here still win
        import presets
        try:
            preset = presets.load(pre.preset)
        except presets.PresetError as e:
            raise SystemExit(str(e))
        ap.set_defaults(**{k: v for k, v in (preset.get("talk") or {}).items()},
                        **{k: preset[k] for k in ("look", "speaker", "role") if preset.get(k)})
    args = ap.parse_args()

    video = Path(args.video).resolve()
    if not video.is_file():
        raise SystemExit(f"file not found: {video}")
    tpath, data, words = load_transcript(video, args.transcript)
    tpath = tpath.resolve()
    t_from, t_to = args.t_from or 0.0, args.t_to
    if args.t_from is not None or t_to is not None:  # one part of a long recording
        words = [w for w in words if t_from <= (w["start"] + w["end"]) / 2 < (t_to if t_to is not None else 1e12)]
        if not words:
            raise SystemExit(f"no words between --from {t_from:g} and --to {t_to}: check the times")
    out = Path(args.out).resolve() if args.out else video.with_suffix(".cut.json")
    base = out.parent
    warnings = []
    if data.get("source_size") and data["source_size"] != video.stat().st_size:
        warnings.append(f"{tpath.name} was made from a different file than {video.name} (size differs)")

    import probe  # same folder; ffprobe/ffmpeg wrappers
    have_ff = bool(shutil.which("ffprobe") and shutil.which("ffmpeg"))
    meta = probe.info(video) if have_ff else {}
    duration = float(meta.get("duration") or data.get("duration") or words[-1]["end"] + 0.5)
    if have_ff and not meta.get("has_audio", True):
        raise SystemExit(f"{video.name} has no audio track")
    silences = []
    if not args.no_silence:
        if have_ff:
            silences = probe.silence(video, meta, args.noise_db, max(0.2, args.max_pause))["silences"]
        else:
            warnings.append("ffmpeg not on PATH: cut from word times only (--no-silence to hide this)")

    drop = {}
    if not args.keep_fillers:
        for i, w in enumerate(words):
            if is_filler(w["word"]):
                drop[i] = ("filler", None)
    if not args.keep_retakes:
        mark_retakes(words, drop)

    ranges, lone = plan_clips(words, drop, duration, args.pad, args.max_pause, silences)
    if not ranges:
        raise SystemExit("nothing left to keep: check the transcript and --max-pause")
    src = rel(video, base)
    clips = [{"in": a, "out": b} for a, b in ranges]
    snapped = snap_words(words, drop, ranges, lone)

    # Where the face is: faces.py (OpenCV) when it is installed, else --face-y or a typical 0.38.
    cw, ch = 1080, 1920
    iw, ih = meta.get("width"), meta.get("height")
    pts, face_report = [], None
    if args.fit == "cover" and args.face_y is None and not args.no_faces and have_ff and iw and ih:
        import faces
        if faces.available():
            f0, f1 = max(0.0, words[0]["start"] - 1), min(duration, words[-1]["end"] + 1)
            pts = faces.track(video, iw, ih, f0, f1)
            total_samples = max(1, int((f1 - f0) * faces.SAMPLE_FPS))
            face_report = faces.summarize(pts, iw, ih, cw, ch, args.punch, total_samples)
            if face_report["found"] < 0.3:
                warnings.append(f"a face was found in only {face_report['found']:.0%} of the frames: "
                                "check the framing in the preview, or pass --face-y")
                if face_report["found"] < 0.1:
                    pts = []
        else:
            warnings.append(f"no face detection: framed for a face at 38% of the height ({faces.INSTALL} to "
                            "centre crops and punch-ins on the face)")
    y_face = 1 - 2 * (args.face_y if args.face_y is not None else 0.38)
    punched_tf = {"scale": round(args.punch, 3), "y": round(y_face * (1 - args.punch), 3)}
    moving = 0

    def frame(a, b, punched):
        """The transform for source a..b: centred on the face found there (following it across a wide
        shot when it moves), or the fixed --face-y framing."""
        nonlocal moving
        if not pts:
            return dict(punched_tf) if punched else {}
        near = [p for p in pts if a - 0.5 <= p[0] <= b + 0.5] or pts
        face = [statistics.median(p[k] for p in near) for k in (1, 2, 3, 4)]
        tf = faces.framing(face, iw, ih, cw, ch, args.punch)[1 if punched else 0]
        if len(near) >= 3 and near is not pts and faces.geometry(iw, ih, cw, ch)[0] > cw * 1.05:
            xs = [faces.framing(p[1:], iw, ih, cw, ch, args.punch)[1 if punched else 0].get("x", 0.0)
                  for p in near]
            if max(xs) - min(xs) > 0.2:
                tf.pop("x", None)
                tf["x_path"] = faces.path_of(near, xs)
                moving += 1
        return tf

    # Framing: alternate wide / punched at a cut once the current framing has held long enough.
    punched, held = False, 0.0
    for n, c in enumerate(clips):
        if n and args.punch > 1 and held >= args.punch_hold:
            punched, held = not punched, 0.0
        c["punched"] = punched
        held += c["out"] - c["in"]

    sentences = sentences_of(words, drop)
    hooks = []
    for s in sentences:
        ws = [words[i] for i in s]
        score, why = score_hook(ws)
        hooks.append({"start": round(ws[0]["start"], 2), "end": round(ws[-1]["end"], 2), "score": score,
                      "text": " ".join(w["word"] for w in ws), "why": why, "_s": s})
    hooks.sort(key=lambda h: -h["score"])

    video_items, skip = [], set()
    teaser = None
    if args.hook_first:
        teaser = next((h for h in hooks if h["end"] - h["start"] <= args.hook_max and h["score"] > 0), None)
        if teaser and teaser["_s"] == sentences[0]:
            warnings.append("--hook-first: the talk already opens on its best line, so no teaser was added")
            teaser = None
        elif teaser:
            a = max(0.0, teaser["start"] - args.pad)
            b = min(duration, teaser["end"] + args.pad)
            item = {"id": "hook", "src": src, "in": round(a, 3), "out": round(b, 3), "fit": args.fit,
                    "note": "teaser: " + teaser["text"][:80]}
            tf = frame(a, b, args.punch > 1)
            if tf:
                item["transform"] = tf
            video_items.append(item)
            skip.update(teaser["_s"][:1])
        else:
            warnings.append("--hook-first: no line scored as a hook within --hook-max; the talk starts as recorded")

    for n, c in enumerate(clips, 1):
        inside = [w["word"] for w in snapped if c["in"] <= (w["start"] + w["end"]) / 2 < c["out"]]
        item = {"id": f"t{n}", "src": src, "in": c["in"], "out": c["out"], "fit": args.fit}
        tf = frame(c["in"], c["out"], c["punched"])
        if tf:
            item["transform"] = tf
        if inside:
            item["note"] = " ".join(inside)[:80]
        video_items.append(item)

    if args.denoise:
        for v in video_items:
            v["denoise"] = True
    timeline_clips = [{"in": v["in"], "out": v["out"]} for v in video_items]
    total = sum(v["out"] - v["in"] for v in video_items)
    slots = []
    if args.broll_every > 0:
        slots = broll_slots(timeline_clips, words, sentences, total, args.broll_every, args.broll_length, skip)
        if teaser:  # the teaser plays the hook's words first; slots belong in the talk after it
            lead = video_items[0]["out"] - video_items[0]["in"]
            slots = [s for s in slots if s["at"] >= lead]

    spec = {"name": args.name or f"{video.stem}-cut"}
    fps = round(float(meta.get("fps") or 0))
    if fps in (24, 25, 30, 50, 60):
        spec["fps"] = fps
    if not args.no_loudness:
        spec["loudness"] = args.loudness
    look_styles, look_captions = {}, {}
    if args.look:
        import looks as looks_mod
        try:
            same = preset.get("look") == args.look  # the preset's colors and fonts belong to its look
            look_styles = looks_mod.styles(args.look, preset.get("brand") if same else None,
                                           preset.get("fonts") if same else None)
        except looks_mod.LookError as e:
            raise SystemExit(str(e))
        for k, st in (preset.get("styles") or {}).items():
            look_styles[k] = {**look_styles.get(k, {}), **st} if isinstance(st, dict) else st
        look_captions = dict(looks_mod.looks()[args.look].get("captions") or {})
        spec["look"] = args.look
    if preset:
        spec["preset"] = pre.preset  # the builder adds its brand colors, fonts, styles, handle and logo
        pc = preset.get("captions") or {}
        look_captions.update({k: v for k, v in pc.items() if k != "keywords"})
        if isinstance(pc.get("keywords"), dict):
            look_captions["keywords"] = {**(look_captions.get("keywords") or {}),
                                         **{k: v for k, v in pc["keywords"].items() if k != "words"}}
    spec["video"] = video_items
    keywords = [] if args.no_keywords else keywords_of(words, sentences)
    if args.speaker or args.role:
        lead = video_items[0]["out"] - video_items[0]["in"] if teaser else 0.0
        spec["texts"] = lower_third(args.speaker, args.role, lead + 0.4, look_styles)
        if face_report and pts and (face_report.get("caption_y") or -1) > -0.45:
            warnings.append("captions were moved up off a low face and may meet the lower third: check the preview")

    overlays = []
    if args.broll and slots:
        files = [Path(f).resolve() for f in args.broll]
        missing = [str(f) for f in files if not f.is_file()]
        if missing:
            raise SystemExit("B-roll file not found: " + ", ".join(missing))
        use = slots if len(files) >= len(slots) else [slots[round(k * len(slots) / len(files))]
                                                         for k in range(len(files))]
        for n, (slot, f) in enumerate(zip(use, files), 1):
            o = {"id": f"b{n}", "src": rel(f, base), "at": slot["at"], "duration": slot["duration"],
                 "fit": "cover", "mute": True, "track": "broll", "note": "says: " + slot["says"][:70]}
            fm = probe.info(f) if have_ff else {}
            fdur = float(fm.get("duration") or 0)
            if fm.get("kind") == "video" and fdur > slot["duration"]:
                o["in"] = round((fdur - slot["duration"]) / 2, 2)  # the middle is steadier than the start
            overlays.append(o)
            slot["filled_with"] = f.name
        if len(files) > len(slots):
            warnings.append(f"{len(files) - len(slots)} B-roll file(s) left over: fewer slots than files")
    elif args.broll:
        warnings.append("no B-roll slots in a talk this short; place the B-roll by hand")
    if overlays:
        spec["overlays"] = overlays
    cut_transcript = None
    if not args.no_captions:
        # The original transcript stays as it is; captions read a copy with the kept words only, their
        # times snapped into the clips (see snap_words).
        cut_transcript = out.with_suffix(".transcript.json")
        copy = {k: v for k, v in data.items() if k != "segments"}
        copy.update(source=str(video), words=snapped, made_by="cut_talk.py from " + tpath.name)
        cut_transcript.write_text(json.dumps(copy, ensure_ascii=False, indent=1), encoding="utf-8")
        spec["captions"] = {"transcript": rel(cut_transcript, base), "max_words": 3}
        # the look's caption settings: words per caption, capitals, the word being said lit up, keywords
        spec["captions"].update({k: v for k, v in look_captions.items() if k != "keywords"})
        if look_captions.get("keywords") and keywords:
            spec["captions"]["keywords"] = dict(look_captions["keywords"], words=keywords)
        cap_y = face_report.get("caption_y") if face_report and pts else None
        if face_report and pts and cap_y is None:
            warnings.append("the face fills the frame: no caption spot clear of it, captions stay low")
        elif cap_y is not None and abs(cap_y - faces.CAPTION_Y) > 0.01:
            spec["styles"] = {"caption": {"y": cap_y}}  # moved off the face
            if not args.look:
                spec["captions"]["style"] = "caption"

    out.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")

    removed = describe_gaps([[v["in"], v["out"]] for v in video_items if v.get("id") != "hook"],
                            words, drop, duration, lone)
    window = None
    if args.t_from is not None or args.t_to is not None:  # only what was cut inside the part used
        window = [min(c["in"] for c in clips), max(c["out"] for c in clips)]
        removed = [dict(r, **{"from": max(r["from"], window[0]), "to": min(r["to"], window[1])})
                   for r in removed if r["to"] > window[0] and r["from"] < window[1]]
        removed = [r for r in removed if r["to"] - r["from"] > 0.05]
    cut_by = {}
    for r in removed:
        cut_by[r["why"]] = round(cut_by.get(r["why"], 0) + r["to"] - r["from"], 2)
    lengths = [c["out"] - c["in"] for c in clips]
    report = {
        "spec": str(out),
        "caption_transcript": str(cut_transcript) if cut_transcript else None,
        "source": str(video),
        "source_seconds": round(duration, 2),
        **({"window": [round(window[0], 2), round(window[1], 2)]} if window else {}),
        "edit_seconds": round(total, 2),
        "cut_seconds": cut_by,
        "clips": len(clips),
        "clip_seconds": {"mean": round(sum(lengths) / len(lengths), 2), "min": round(min(lengths), 2),
                         "max": round(max(lengths), 2)},
        "punched_clips": sum(1 for c in clips if c["punched"]),
        "keywords": {"words": keywords,
                     "used": bool(spec.get("captions", {}).get("keywords")),
                     "how": "colored in the captions" if spec.get("captions", {}).get("keywords") else
                            "not used: pass --look edu or talk, or put them in captions.keywords"},
        "faces": ({"found": face_report["found"], "face": face_report["face"],
                   "caption_y": face_report.get("caption_y"), "title_y": face_report.get("title_y"),
                   "clips_following_face": moving} if face_report and pts else
                  {"found": 0.0, "framed_for_face_y": args.face_y if args.face_y is not None else 0.38}),
        "teaser": {k: teaser[k] for k in ("start", "end", "text")} if teaser else None,
        "hooks": [{k: v for k, v in h.items() if k != "_s"} for h in hooks[:max(0, args.hooks)]],
        "broll_slots": slots,
        "removed": removed,
        "warnings": warnings,
        "next": f"python build_draft.py {out.name} --check, read the timeline, then build",
    }
    text = json.dumps(report, ensure_ascii=False, indent=1)
    text = re.sub(r"\[\s+([^\[\]{}]*?)\s+\]", lambda m: "[" + " ".join(m.group(1).split()) + "]", text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

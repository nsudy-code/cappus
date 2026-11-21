#!/usr/bin/env python3
"""Find the best short clips in a long recording (podcast, kajian, class, interview) and cut each one
into its own talking-head spec.

  shorts.py long.mp4                          # needs long.transcript.json beside it (transcribe.py)
  shorts.py long.mp4 --count 5 --max 45       # five shorts, none longer than 45 s
  shorts.py long.mp4 --list                   # only rank the candidates, write nothing
  shorts.py long.mp4 --look talk --preset dr-aisya --denoise   # anything else goes to cut_talk.py

A short starts at a sentence that grabs (a claim, a number, a question, talking to the viewer), not
mid-thought ("and so...", "itu tadi..."), runs through whole sentences without a long break, and
ends on a finished sentence. Each pick becomes <video>.short<N>.cut.json through cut_talk.py
(jump cuts, punch-ins, captions, face framing), named <video>-short<N> in CapCut.

Prints JSON: each short with its source times, length, score and why, its opening line, and the
spec written. Read the opening lines: the first seconds decide whether anyone keeps watching.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import cut_talk as ct

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
# A sentence starting with these continues something said before it: a short can't open there.
CONNECTORS = {"dan", "jadi", "terus", "trus", "tapi", "tetapi", "karena", "karna", "makanya", "sehingga",
              "lalu", "kemudian", "juga", "atau", "nah", "nha", "and", "so", "but", "because", "then",
              "also", "or", "which", "anyway"}
POINTERS = {"itu", "ini", "tadi", "dia", "mereka", "beliau", "tersebut", "it", "this", "that", "they", "he",
            "she", "those", "these"}
TOPIC_BREAK = 2.5   # seconds of silence between sentences that ends a short


def opener(ws) -> tuple:
    """(penalty, why) for a sentence that leans on what came before it."""
    toks = [ct.norm(w["word"]) for w in ws[:2]]
    if toks and toks[0] in CONNECTORS:
        return -2.5, f"starts mid-thought (\"{ws[0]['word']}\")"
    if toks and toks[0] in POINTERS:
        return -1.0, f"points back (\"{ws[0]['word']}\")"
    return 0.0, None


def candidates(words, sentences, lo, hi, target):
    """Every run of whole sentences lo..hi seconds long, scored."""
    scored = [ct.score_hook([words[i] for i in s]) for s in sentences]
    out = []
    for i, first in enumerate(sentences):
        ws0 = [words[k] for k in first]
        pen, why_open = opener(ws0)
        for j in range(i, len(sentences)):
            if j > i and words[sentences[j][0]]["start"] - words[sentences[j - 1][-1]]["end"] > TOPIC_BREAK:
                break
            a, b = words[first[0]]["start"], words[sentences[j][-1]]["end"]
            length = b - a
            if length > hi:
                break
            if length < lo:
                continue
            hook, hook_why = scored[i]
            body = [max(0.0, scored[k][0]) for k in range(i + 1, j + 1)]
            last = words[sentences[j][-1]]["word"].rstrip()
            n_words = sum(len(sentences[k]) for k in range(i, j + 1))
            pace = n_words / max(length, 0.1)
            score = 1.5 * hook + pen + 0.5 * (sum(body) / len(body) if body else 0)
            why = [f"opens with: {', '.join(hook_why) or 'a plain line'}"]
            if why_open:
                why.append(why_open)
            if last[-1:] in ".!":
                score += 1.0
                why.append("ends on a finished sentence")
            elif last[-1:] != "?":
                score -= 1.0
                why.append("ends mid-sentence")
            if pace < 1.6:
                score -= 1.0
                why.append(f"slow ({pace:.1f} words/s)")
            score -= abs(length - target) / 15
            out.append({"from": round(a, 2), "to": round(b, 2), "seconds": round(length, 1),
                        "score": round(score, 2), "why": why, "_i": i, "_j": j,
                        "opening": " ".join(w["word"] for w in ws0)[:160],
                        "topic": ct.content_words([words[k] for s in sentences[i:j + 1] for k in s])})
    return out


def pick(cands, count, gap=2.0):
    """The best ones that do not overlap."""
    chosen = []
    for c in sorted(cands, key=lambda c: -c["score"]):
        if all(c["to"] + gap <= o["from"] or o["to"] + gap <= c["from"] for o in chosen):
            chosen.append(c)
        if len(chosen) == count:
            break
    return chosen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--transcript", help="default: <video>.transcript.json beside it")
    ap.add_argument("--count", type=int, default=3, help="how many shorts (3)")
    ap.add_argument("--min", dest="lo", type=float, default=20.0, help="shortest, in seconds of speech (20)")
    ap.add_argument("--max", dest="hi", type=float, default=60.0, help="longest (60)")
    ap.add_argument("--target", type=float, default=35.0, help="the length to aim for (35)")
    ap.add_argument("--list", action="store_true", help="only rank the candidates; write no specs")
    ap.add_argument("--out-dir", help="where the specs go (default: beside the video)")
    args, passthrough = ap.parse_known_args()
    if not 5 <= args.lo <= args.hi:
        raise SystemExit("--min must be at least 5 and not above --max")
    for flag in ("--out", "--name", "--from", "--to", "--transcript"):
        if flag in passthrough:
            raise SystemExit(f"{flag} is set by shorts.py for each short")

    video = Path(args.video).resolve()
    if not video.is_file():
        raise SystemExit(f"file not found: {video}")
    tpath, data, words = ct.load_transcript(video, args.transcript)
    drop = {i: ("filler", None) for i, w in enumerate(words) if ct.is_filler(w["word"])}
    sentences = ct.sentences_of(words, drop)
    cands = candidates(words, sentences, args.lo, args.hi, args.target)
    if not cands:
        spoken = words[-1]["end"] - words[0]["start"]
        raise SystemExit(f"no run of whole sentences {args.lo:g}-{args.hi:g} s long in {spoken:.0f} s of speech: "
                         "try a smaller --min or a larger --max")
    chosen = pick(cands, max(1, args.count))
    out_dir = Path(args.out_dir).resolve() if args.out_dir else video.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    shorts = []
    for n, c in enumerate(sorted(chosen, key=lambda c: c["from"]), 1):
        item = {k: v for k, v in c.items() if not k.startswith("_")}
        item["rank"] = sorted(chosen, key=lambda c: -c["score"]).index(c) + 1
        if not args.list:
            spec = out_dir / f"{video.stem}.short{n}.cut.json"
            cmd = [sys.executable, str(HERE / "cut_talk.py"), str(video), "--transcript", str(tpath),
                   "--from", f"{max(0.0, c['from'] - 0.3):.2f}", "--to", f"{c['to'] + 0.3:.2f}",
                   "--out", str(spec), "--name", f"{video.stem}-short{n}", *passthrough]
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if res.returncode != 0:
                item["error"] = (res.stderr or res.stdout).strip()[-600:]
            else:
                rep = json.loads(res.stdout)
                item.update(spec=str(spec), edit_seconds=rep["edit_seconds"], clips=rep["clips"],
                            hooks=[h["text"] for h in rep.get("hooks", [])[:2]],
                            warnings=rep.get("warnings", []))
        shorts.append(item)
    if any("error" in s for s in shorts) and all("error" in s for s in shorts):
        print(json.dumps({"shorts": shorts}, ensure_ascii=False, indent=1))
        return 1
    report = {
        "source": str(video),
        "spoken_seconds": round(words[-1]["end"] - words[0]["start"], 1),
        "candidates": len(cands),
        "shorts": shorts,
        "next": ("read each opening line; build the ones worth posting: python build_draft.py "
                 "<spec> --check, then without --check" if not args.list else
                 "run again without --list to write the specs"),
    }
    text = json.dumps(report, ensure_ascii=False, indent=1)
    text = re.sub(r"\[\s+([^\[\]{}]*?)\s+\]", lambda m: "[" + " ".join(m.group(1).split()) + "]", text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

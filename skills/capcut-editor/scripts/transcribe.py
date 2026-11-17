#!/usr/bin/env python3
"""Transcribe speech into word timings, for captions and for cutting by what is said.

  transcribe.py talk.mp4                          # writes talk.transcript.json next to the file
  transcribe.py talk.mp4 --language id            # skip language detection (id, en, ms, ...)
  transcribe.py talk.mp4 --model large-v3-turbo   # slower, more accurate (default: small)
  transcribe.py talk.mp4 --prompt "Cappus, CapCut, Ubud"   # spellings of names and jargon
  transcribe.py talk.mp4 --srt                    # also write talk.srt

Runs offline with faster-whisper, an optional dependency:
  python -m pip install -r requirements-captions.txt
The first use of a model downloads it once (tiny ~75 MB, base ~145 MB, small ~0.5 GB,
medium ~1.5 GB, large-v3-turbo ~1.6 GB, large-v3 ~3 GB). After that no network is needed.

Times in the transcript are positions in the source file. Use it in a spec with
  "captions": {"transcript": "talk.transcript.json", "style": "caption"}
and the builder maps every word onto the timeline through the clips that play that file, so the
captions stay in sync after cuts. Output (stdout) is a JSON summary with the text by segment.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SAMPLE_RATE = 16000
REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements-captions.txt"


def load_audio(path: Path):
    """Decode any media file to 16 kHz mono float32 with ffmpeg."""
    import numpy as np
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
           "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True)
    except FileNotFoundError:
        raise SystemExit("ffmpeg is not on PATH")
    if r.returncode != 0 or not r.stdout:
        err = r.stderr.decode("utf-8", "replace").strip()[-300:]
        raise SystemExit(f"cannot read audio from {path}: {err or 'the file has no audio track'}")
    return np.frombuffer(r.stdout, np.float32)


def clean_words(segments_words):
    """Strip spaces, fold stray punctuation into the previous word, fix zero-length words."""
    words = []
    for w in segments_words:
        text = (w.word or "").strip()
        if not text:
            continue
        start, end = round(float(w.start), 3), round(float(w.end), 3)
        if words and not re.search(r"\w", text):
            words[-1]["word"] += text
            continue
        if end <= start:
            end = round(start + 0.05, 3)
        words.append({"word": text, "start": start, "end": end, "p": round(float(w.probability), 2)})
    return words


def srt_cues(words, max_chars=42, max_gap=0.8):
    """Subtitle-sized cues: split at pauses and sentence ends, then into lines of even length."""
    phrases, cur = [], []
    for w in words:
        if cur and (w["start"] - cur[-1]["end"] > max_gap or cur[-1]["word"][-1:] in ".?!"):
            phrases.append(cur)
            cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)

    def cue(chunk):
        return {"start": chunk[0]["start"], "end": chunk[-1]["end"],
                "text": " ".join(x["word"] for x in chunk)}

    cues = []
    for ph in phrases:
        parts = max(1, math.ceil(len(cue(ph)["text"]) / max_chars))
        target = len(cue(ph)["text"]) / parts
        chunk, made = [], 0
        for w in ph:
            chunk.append(w)
            size = len(cue(chunk)["text"])
            if made < parts - 1 and (size >= target or (w["word"][-1:] in ",;:" and size >= 0.6 * target)):
                cues.append(cue(chunk))
                chunk, made = [], made + 1
        if chunk:
            cues.append(cue(chunk))
    return cues


def stamp(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def write_srt(path: Path, words, joiner=" "):
    cues = srt_cues(words)
    lines = []
    for n, c in enumerate(cues, 1):
        text = c["text"] if joiner == " " else c["text"].replace(" ", "")
        lines += [str(n), f"{stamp(c['start'])} --> {stamp(c['end'])}", text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def summary(data: dict, out: Path, srt: Path | None, reused: bool) -> dict:
    low = [f"{w['start']:.2f} {w['word']}" for w in data["words"] if w.get("p", 1) < 0.5]
    rep = {
        "transcript": str(out),
        **({"srt": str(srt)} if srt else {}),
        **({"reused": "existing transcript of this exact file and model; pass --force to redo it"}
           if reused else {}),
        "source": data["source"],
        "language": data["language"],
        "model": data["model"],
        "duration": data["duration"],
        "words": len(data["words"]),
        "low_confidence": low[:40],
        "text": [f"{s['start']:7.2f} - {s['end']:7.2f}  {'(?) ' if s.get('suspect') else ''}{s['text']}"
                 for s in data["segments"]],
    }
    if any(s.get("suspect") for s in data["segments"]):
        rep["suspect_note"] = "(?) marks text Whisper may have invented over music or silence; check it."
    if not data["words"]:
        rep["warning"] = "no speech found"
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("media", help="video or audio file with speech")
    ap.add_argument("--model", default="small",
                    help="tiny, base, small (default), medium, large-v3-turbo or large-v3")
    ap.add_argument("--language", help="language code such as id or en (default: detect)")
    ap.add_argument("--prompt", help="text that shows the spelling of names and terms")
    ap.add_argument("--out", help="transcript path (default: <media>.transcript.json beside the media)")
    ap.add_argument("--srt", action="store_true", help="also write an .srt beside the transcript")
    ap.add_argument("--device", default="cpu", help="cpu (default) or cuda (needs NVIDIA CUDA libraries)")
    ap.add_argument("--force", action="store_true", help="transcribe again even if a transcript exists")
    args = ap.parse_args()

    media = Path(args.media).resolve()
    if not media.is_file():
        print(f"ERROR: file not found: {media}", file=sys.stderr)
        return 1
    if args.out:
        out = Path(args.out).resolve()
    else:
        out = media.with_name(media.stem + ".transcript.json")
        try:  # talk.mp4 and talk.wav side by side: keep the extension in the second one's name
            if out.is_file() and json.loads(out.read_text(encoding="utf-8")).get("source") != str(media):
                out = media.with_name(media.name + ".transcript.json")
        except (OSError, ValueError):
            pass
    srt = None
    if args.srt:
        tail = ".transcript.json"
        srt = out.with_name(out.name[:-len(tail)] + ".srt") if out.name.endswith(tail) else out.with_suffix(".srt")
    st = media.stat()

    if out.is_file() and not args.force:
        try:
            old = json.loads(out.read_text(encoding="utf-8"))
            same = (old.get("source") == str(media) and old.get("model") == args.model
                    and old.get("source_size") == st.st_size and old.get("source_mtime") == int(st.st_mtime)
                    and (not args.language or old.get("language") == args.language)
                    and old.get("prompt") == args.prompt)
        except (OSError, ValueError):
            same = False
        if same:
            if srt:
                write_srt(srt, old["words"], old.get("joiner", " "))
            print(json.dumps(summary(old, out, srt, True), ensure_ascii=False, indent=1))
            return 0

    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper is not installed for this Python interpreter (it is optional, for captions).\n"
              f"Run:  {sys.executable} -m pip install -r \"{REQUIREMENTS}\"", file=sys.stderr)
        return 3

    audio = load_audio(media)
    began = time.time()
    compute = "int8" if args.device == "cpu" else "float16"
    try:
        model = WhisperModel(args.model, device=args.device, compute_type=compute)
    except Exception as e:
        print(f"ERROR: cannot load model '{args.model}': {e}", file=sys.stderr)
        return 1
    segments, info = model.transcribe(
        audio, language=args.language, initial_prompt=args.prompt, word_timestamps=True,
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False, beam_size=5)

    segs, raw_words, step = [], [], 0
    for s in segments:
        text = s.text.strip()
        if not text:
            continue
        seg = {"start": round(s.start, 3), "end": round(s.end, 3), "text": text}
        # Whisper sometimes invents text over music or silence; these markers flag likely cases.
        if s.compression_ratio > 2.4 or (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0):
            seg["suspect"] = True
        segs.append(seg)
        raw_words += s.words or []
        if info.duration and s.end / info.duration * 10 >= step + 1:
            step = int(s.end / info.duration * 10)
            print(f"transcribed {s.end:.0f} of {info.duration:.0f} s", file=sys.stderr, flush=True)

    lang = info.language
    joiner = "" if lang in {"zh", "ja", "yue", "th", "lo", "my", "km", "bo"} else " "
    data = {
        "source": str(media), "source_size": st.st_size, "source_mtime": int(st.st_mtime),
        "language": lang, "language_probability": round(info.language_probability, 3),
        "joiner": joiner, "duration": round(info.duration, 3), "model": args.model,
        "prompt": args.prompt, "seconds_taken": round(time.time() - began, 1),
        "segments": segs, "words": clean_words(raw_words),
    }
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    if srt:
        write_srt(srt, data["words"], joiner)
    print(json.dumps(summary(data, out, srt, False), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

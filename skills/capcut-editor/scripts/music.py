#!/usr/bin/env python3
"""Make a royalty-free music bed whose beats are known exactly, for edits that have no music.

  music.py out.wav --mood hype --bpm 124 --length 30 --drop 4 --breath 15 --end-hit 24
  music.py out.wav --mood chill --bpm 88 --length 20

Writes out.wav and out.beats.json: bpm, every beat and downbeat, and the sections (intro, drop,
breath, end). Use those times for cuts and text changes instead of probe.py --beats, which can
lock onto half or two-thirds of the real tempo on synthetic or sparse music.

Moods: hype (four-on-the-floor, claps, rolling bass), corporate (light kick, snaps, plucked arps),
chill (lo-fi: swung hats, soft keys), cinematic (no hats; drums on the bar, a big boom on hits).
The track is generated here, so it is free to use anywhere. It is a solid bed, not a song: when the
user has a licensed track or picks one from CapCut's library with the same BPM, the edit stays in
sync as long as the song's first downbeat is placed at 0 and its drop at --drop.
"""
from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
MOODS = ("hype", "corporate", "chill", "cinematic")
# chord progressions (root in bass octave, three chord tones), one chord per bar
PROG = {
    "minor": [(55.00, (220.0, 261.6, 329.6)), (43.65, (174.6, 220.0, 261.6)),
              (65.41, (261.6, 329.6, 392.0)), (49.00, (196.0, 246.9, 293.7))],   # Am F C G
    "major": [(65.41, (261.6, 329.6, 392.0)), (49.00, (196.0, 246.9, 293.7)),
              (55.00, (220.0, 261.6, 329.6)), (43.65, (174.6, 220.0, 261.6))],   # C G Am F
}


class Mixer:
    def __init__(self, length, seed=7):
        self.buf = np.zeros(int(SR * (length + 1.0)))
        self.rng = np.random.default_rng(seed)
        self.length = length

    def place(self, sound, t, gain=1.0):
        if t < 0 or t >= self.length:
            return
        i = int(round(t * SR))
        j = min(len(self.buf), i + len(sound))
        self.buf[i:j] += sound[: j - i] * gain

    def noise(self, n):
        return self.rng.standard_normal(n)


def env(n, decay):
    return np.exp(-np.arange(n) / (decay * SR))


def smooth(x, k):
    """A cheap low-pass: moving average over k samples."""
    return np.convolve(x, np.ones(k) / k, mode="same")


def kick(mx, punch=1.0):
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    freq = 45 + 110 * punch * np.exp(-t * 28)
    return np.sin(2 * np.pi * np.cumsum(freq) / SR) * env(n, 0.12) + 0.3 * np.sin(2 * np.pi * 50 * t) * env(n, 0.2)


def clap(mx, soft=False):
    n = int(0.25 * SR)
    nz = np.convolve(mx.noise(n), [1, -0.8], mode="same")
    out = np.zeros(n)
    for k, off in enumerate((0, 0.012, 0.024)):
        i = int(off * SR)
        out[i:] += nz[: n - i] * env(n - i, 0.05 if k == 2 else 0.008)
    return smooth(out, 6) * 0.4 if soft else out * 0.5


def hat(mx, open_=False, gain=0.35):
    n = int((0.18 if open_ else 0.05) * SR)
    nz = mx.noise(n)
    nz = nz - smooth(nz, 4)
    return nz * env(n, 0.06 if open_ else 0.012) * gain


def tone(freq, dur, shape="saw", decay=None, detune=0.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    if shape == "saw":
        w = 2 * ((freq * t) % 1.0) - 1
        if detune:
            w = 0.5 * w + 0.5 * (2 * ((freq * (1 + detune) * t) % 1.0) - 1)
    elif shape == "keys":  # sine with a soft second harmonic
        w = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(4 * np.pi * freq * t)
    else:
        w = np.sin(2 * np.pi * freq * t)
    attack = np.minimum(1, np.arange(n) / (0.005 * SR))
    release = np.minimum(1, (n - np.arange(n)) / (0.02 * SR))
    out = w * attack * release
    return out * (env(n, decay) if decay else 1)


def riser(mx, dur):
    n = int(dur * SR)
    if n < 12:  # too short to smooth; nothing to hear anyway
        return np.zeros(0)
    nz = mx.noise(n)
    nz = nz - smooth(nz, 6)
    return nz * np.linspace(0, 1, n) ** 2 * 0.25


def boom(mx):
    out = tone(55, 1.4, "sine", 0.45) * 0.9
    swell = riser(mx, 0.3)[::-1] * 0.8
    out[: len(swell)] += swell
    return out


def render(mood, bpm, length, drop, breath, end_hit, seed=7):
    beat = 60.0 / bpm
    bar = 4 * beat
    mx = Mixer(length, seed)
    prog = PROG["major" if mood in ("corporate",) else "minor"]
    swing = beat / 2 * (0.16 if mood == "chill" else 0.0)

    def section(t):
        if t < drop:
            return "intro"
        if breath is not None and breath <= t < breath + bar:
            return "breath"
        return "groove"

    nbars = int(np.ceil(length / bar))
    for b in range(nbars):
        t0 = b * bar
        root, chord = prog[b % 4]
        # pads / keys
        if mood == "chill":
            for k, f in enumerate(chord):
                mx.place(tone(f, bar * 0.95, "keys", 1.2), t0 + k * 0.015, 0.06)
        elif mood == "cinematic":
            for f in chord:
                mx.place(smooth(tone(f / 2, bar, "saw", None, 0.006), 40) * np.linspace(0.6, 1, int(bar * SR)), t0, 0.05)
        else:
            for f in chord:
                mx.place(tone(f, bar, "sine") * np.linspace(1, 0.7, int(bar * SR)), t0, 0.045)
        for step in range(8):  # eighth notes
            t = t0 + step * beat / 2 + (swing if step % 2 else 0)
            sec = section(t)
            if mood in ("hype", "corporate") or (mood == "chill" and sec != "breath"):
                if step % 2 == 1:
                    mx.place(hat(mx, open_=(step == 7 and mood == "hype"), gain=0.35 if mood != "chill" else 0.2),
                             t, 0.8 if sec == "groove" else 0.5)
            if mood == "corporate" and sec != "breath":  # plucked arpeggio
                f = chord[step % 3] * (2 if step % 4 == 3 else 1)
                mx.place(tone(f, beat / 2, "keys", 0.12), t, 0.09 if sec == "groove" else 0.06)
            if mood in ("hype", "corporate", "chill"):
                if sec == "intro" and step % 2 == 0:
                    mx.place(smooth(tone(root * 2, beat / 2, "saw", 0.12), 30), t, 0.3)
                elif sec == "groove":
                    if mood == "hype":
                        note = root * (2 if step % 4 != 3 else 3)
                        mx.place(smooth(tone(note, beat / 2 * 0.9, "saw", 0.09), 25), t, 0.45 * (0.6 if step % 2 == 0 else 1.0))
                    elif step % 2 == 0:
                        mx.place(smooth(tone(root * 2, beat * 0.9, "saw", 0.2), 40), t, 0.4)
        for k in range(4):
            t = t0 + k * beat
            sec = section(t)
            if sec != "groove":
                continue
            if mood == "hype":
                mx.place(kick(mx), t, 0.9)
                if k in (1, 3):
                    mx.place(clap(mx), t, 0.7)
            elif mood == "corporate":
                mx.place(kick(mx, 0.7), t, 0.55)
                if k in (1, 3):
                    mx.place(clap(mx, soft=True), t, 0.6)
            elif mood == "chill":
                if k in (0, 2):
                    mx.place(kick(mx, 0.6), t, 0.6)
                if k == 2:
                    mx.place(kick(mx, 0.6), t + beat / 2 + swing, 0.35)
                if k in (1, 3):
                    mx.place(clap(mx, soft=True), t, 0.5)
            elif mood == "cinematic" and k in (0, 2):
                mx.place(tone(70 if k == 0 else 62, 0.6, "sine", 0.18), t, 0.7)
                mx.place(smooth(mx.noise(int(0.08 * SR)), 30) * env(int(0.08 * SR), 0.03), t, 0.4)
    if mood == "chill":
        mx.place(smooth(mx.noise(int(length * SR)), 3) * 0.012, 0)  # vinyl hiss
    # risers and hits
    mx.place(riser(mx, min(drop, 4.0)), drop - min(drop, 4.0), 1.0)
    if breath is not None:
        mx.place(riser(mx, bar * 0.5), breath + bar * 0.5, 1.3)
    hits = [drop] + ([end_hit] if end_hit is not None else [])
    if end_hit is not None and mood != "chill":
        for k in range(8):
            mx.place(clap(mx), end_hit - beat * 2 + k * beat / 4, 0.25 + 0.05 * k)
    for t in hits:
        mx.place(boom(mx), t, 0.7 if mood != "chill" else 0.35)

    out = mx.buf[: int(length * SR)]
    fade = int(min(2.0, length / 6) * SR)
    out[-fade:] *= np.linspace(1, 0, fade) ** 1.5
    out = np.tanh(out * 1.4)
    out /= max(np.max(np.abs(out)), 1e-9) / 0.89
    return out


def beat_map(bpm, length, drop, breath, end_hit):
    beat = 60.0 / bpm
    bar = 4 * beat
    beats = [round(i * beat, 3) for i in range(int(length / beat) + 1) if i * beat < length]
    sections = [{"name": "intro", "start": 0.0, "end": drop}]
    groove_end = end_hit if end_hit is not None else length
    if breath is not None:
        sections += [{"name": "drop", "start": drop, "end": breath},
                     {"name": "breath", "start": breath, "end": round(breath + bar, 3)},
                     {"name": "groove", "start": round(breath + bar, 3), "end": groove_end}]
    else:
        sections.append({"name": "drop", "start": drop, "end": groove_end})
    if end_hit is not None:
        sections.append({"name": "end", "start": end_hit, "end": length})
    return {"bpm": bpm, "beat": round(beat, 4), "bar": round(bar, 4), "length": length, "drop": drop,
            "breath": breath, "end_hit": end_hit, "beats": beats, "downbeats": beats[::4], "sections": sections,
            "note": "Times are exact (the track was generated on this grid). Cut on downbeats, change text on beats."}


def snap(t, bar):
    return round(round(t / bar) * bar, 3)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", help="output .wav path")
    ap.add_argument("--mood", choices=MOODS, default="hype")
    ap.add_argument("--bpm", type=float, default=120)
    ap.add_argument("--length", type=float, default=30, help="seconds")
    ap.add_argument("--drop", type=float, help="seconds; snapped to a bar, at least the first bar (default: 2 bars in)")
    ap.add_argument("--breath", type=float, help="start of a one-bar breath (kick out, riser), snapped to a bar")
    ap.add_argument("--end-hit", type=float, help="a big hit for the end card, snapped to a bar")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    if not 60 <= args.bpm <= 180:
        print("--bpm must be between 60 and 180", file=sys.stderr)
        return 2
    if not 4 <= args.length <= 180:
        print("--length must be between 4 and 180 seconds", file=sys.stderr)
        return 2
    bar = 240.0 / args.bpm
    drop = snap(args.drop if args.drop is not None else 2 * bar, bar)
    drop_note = None
    if drop < bar:  # a drop at 0 leaves no intro and no room for the riser
        drop_note = f"--drop {args.drop}s snapped up to the first bar ({round(bar, 3)}s); the drop needs an intro bar"
        drop = round(bar, 3)
    breath = snap(args.breath, bar) if args.breath is not None else None
    end_hit = snap(args.end_hit, bar) if args.end_hit is not None else None
    for name, t in (("drop", drop), ("breath", breath), ("end-hit", end_hit)):
        if t is not None and not 0 <= t < args.length:
            print(f"--{name} {t}s is outside the track", file=sys.stderr)
            return 2
    if breath is not None and not drop < breath < (end_hit or args.length) - bar:
        print("--breath must come after the drop and end a bar before the end hit", file=sys.stderr)
        return 2
    audio = render(args.mood, args.bpm, args.length, drop, breath, end_hit, args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.stack([audio, audio], axis=1) * 32767).astype("<i2").tobytes())
    beats = beat_map(args.bpm, args.length, drop, breath, end_hit)
    beats_path = out.with_suffix(".beats.json")
    beats_path.write_text(json.dumps(beats, indent=1), encoding="utf-8")
    print(json.dumps({"wav": str(out), "beats": str(beats_path), "mood": args.mood, "bpm": args.bpm,
                      "drop": drop, "breath": breath, "end_hit": end_hit,
                      "sections": beats["sections"], **({"drop_note": drop_note} if drop_note else {})}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

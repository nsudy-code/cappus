#!/usr/bin/env python3
"""Make a small royalty-free sound-effect kit, each sound with its exact peak time.

  sfx.py                 # write the kit to ~/.cappus/sfx (build_draft.py does this on first use)
  sfx.py --out DIR       # write it somewhere else
  sfx.py --list          # print the sounds, takes and peak times

Sounds (takes): whoosh (3), pop (2), tick (2), hit (2), riser (1). Each take is a WAV plus its
peak time in sfx.json: the moment the sound was built around (the middle of a whoosh, the attack of
a pop or hit, the top of a riser). build_draft.py places a sound so that this peak lands one frame after the
picture it belongs to, which is where an editor puts it by ear. Repeats of a sound rotate through
its takes so two whooshes in a row do not sound copy-pasted.

Every sound is synthesized here with numpy, so the kit is free to use anywhere. The files are
levelled to sit with music.py's tracks at the same volume; build_draft.py then sets each one a few
dB over the music under it.
"""
from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
VERSION = 1  # bump when a sound changes, so cached kits are regenerated
MANIFEST = "sfx.json"
TARGET_RMS = 0.22  # 50 ms RMS around the peak, close to a music.py bed's loud parts
CEILING = 0.89


def env(n, decay):
    return np.exp(-np.arange(n) / (decay * SR))


def smooth(x, k):
    """A cheap low-pass: moving average over k samples."""
    return np.convolve(x, np.ones(k) / k, mode="same")


def bandpass_sweep(noise, freqs, q):
    """Noise through a band-pass whose centre follows freqs (one value per sample).
    A Chamberlin state-variable filter, recomputed per sample so the sweep is smooth."""
    out = np.empty_like(noise)
    low = band = 0.0
    damp = 1.0 / q
    f = 2 * np.sin(np.pi * np.minimum(freqs, SR / 6) / SR)
    for i, x in enumerate(noise):
        high = x - low - damp * band
        band += f[i] * high
        low += f[i] * band
        out[i] = band
    return out


def whoosh(rng, dur, peak, f_lo, f_hi, q, pan):
    """Air moving past: band-passed noise that swells to the peak and falls away faster, its pitch
    rising into the peak and dropping after, panned across the stereo field."""
    n = int(dur * SR)
    t = np.arange(n) / n
    rise = np.clip(t / peak, 0, 1)
    fall = np.clip((1 - t) / (1 - peak), 0, 1)
    shape = np.where(t < peak, rise ** 2.2, fall ** 1.4)
    freqs = f_lo + (f_hi - f_lo) * shape
    body = bandpass_sweep(rng.standard_normal(n), freqs, q)
    air = rng.standard_normal(n)
    air = (air - smooth(air, 3)) * 0.12  # a little hiss on top
    mono = (body + air * shape) * shape
    side = np.clip(0.5 + pan * (t - peak) / max(peak, 1 - peak), 0, 1)  # moves across as it passes
    return np.stack([mono * np.sqrt(1 - side), mono * np.sqrt(side)], axis=1)


def pop(rng, f0, f1):
    """A bubble pop for text appearing: a sine that drops in pitch fast, with a soft click."""
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    freq = f1 + (f0 - f1) * np.exp(-t * 90)
    out = np.sin(2 * np.pi * np.cumsum(freq) / SR) * env(n, 0.03)
    click = rng.standard_normal(n) * env(n, 0.0015) * 0.3
    attack = np.minimum(1, np.arange(n) / (0.002 * SR))
    return (out + smooth(click, 3)) * attack


def tick(rng, freq):
    """A soft tick for a counter, a cursor or a small UI change: a short high blip, rounded off."""
    n = int(0.06 * SR)
    t = np.arange(n) / SR
    blip = np.sin(2 * np.pi * freq * t) * env(n, 0.008)
    nz = rng.standard_normal(n)
    nz = (nz - smooth(nz, 5)) * env(n, 0.003) * 0.4
    attack = np.minimum(1, np.arange(n) / (0.001 * SR))
    return smooth(blip + nz, 4) * attack


def hit(rng, f_top, tail):
    """An impact for a title slam or the drop: a falling sub boom, a burst of noise for the crack,
    and a low tail."""
    n = int((tail + 0.2) * SR)
    t = np.arange(n) / SR
    freq = 38 + (f_top - 38) * np.exp(-t * 22)
    boom = np.sin(2 * np.pi * np.cumsum(freq) / SR) * env(n, tail * 0.35)
    crack = smooth(rng.standard_normal(n), 6) * env(n, 0.02) * 0.7
    rumble = smooth(rng.standard_normal(n), 120) * env(n, tail * 0.3) * 4.0
    attack = np.minimum(1, np.arange(n) / (0.003 * SR))
    return np.tanh((boom + crack + rumble) * 1.6) * attack


def riser(rng, dur):
    """Tension into a reveal: noise and a sine that both climb, getting louder up to the very end
    (the peak), then a quick 30 ms release."""
    n = int(dur * SR)
    t = np.arange(n) / n
    freqs = 300 * (12 ** t)
    nz = bandpass_sweep(rng.standard_normal(n), freqs * 2, 2.0)
    tone = np.sin(2 * np.pi * np.cumsum(freqs) / SR) * 0.35
    out = (nz + tone) * t ** 2.5
    rel = int(0.03 * SR)
    return np.concatenate([out, out[-1] * np.linspace(1, 0, rel) * np.ones(rel)])


# name -> takes: (description, function(rng) -> samples, peak seconds). The peak is where the sound
# was built to land: the middle of a whoosh's swell, the attack of a pop, tick or hit, the top of a riser.
SOUNDS = {
    "whoosh": [
        ("airy, medium (0.7 s)", lambda r: whoosh(r, 0.7, 0.55, 350, 2400, 2.2, 0.8), 0.7 * 0.55),
        ("deep, slower (0.9 s)", lambda r: whoosh(r, 0.9, 0.6, 180, 1300, 1.8, -0.8), 0.9 * 0.6),
        ("bright, fast (0.5 s)", lambda r: whoosh(r, 0.5, 0.5, 600, 4200, 2.6, 0.6), 0.5 * 0.5),
    ],
    "pop": [
        ("mid pop", lambda r: pop(r, 900, 320), 0.003),
        ("higher pop", lambda r: pop(r, 1250, 450), 0.003),
    ],
    "tick": [
        ("soft tick", lambda r: tick(r, 2800), 0.002),
        ("lower tick", lambda r: tick(r, 2100), 0.002),
    ],
    "hit": [
        ("big impact, long tail", lambda r: hit(r, 150, 1.1), 0.004),
        ("tight impact", lambda r: hit(r, 190, 0.6), 0.004),
    ],
    "riser": [
        ("2 s riser that peaks at its end", lambda r: riser(r, 2.0), 2.0),
    ],
}


def level(audio, peak):
    """Scale so the 50 ms around the peak has TARGET_RMS, then keep the peaks under CEILING."""
    i = int(peak * SR)
    w = int(0.025 * SR)
    win = audio[max(0, i - w): i + w]
    rms = float(np.sqrt(np.mean(win ** 2))) or 1e-9
    top = float(np.max(np.abs(audio))) or 1e-9
    gain = min(TARGET_RMS / rms, 1.5 * CEILING / top)  # short clicks: limit how hard they are driven
    out = audio * gain
    if top * gain > CEILING:  # round the peaks off rather than clipping them
        out = np.tanh(out / CEILING)
        out *= CEILING / float(np.max(np.abs(out)))
    return out


def render(name, take, seed=11):
    """(stereo samples, peak seconds) for one take (0-based)."""
    rng = np.random.default_rng(seed + 100 * take + sum(map(ord, name)))
    _, make, peak = SOUNDS[name][take]
    audio = make(rng)
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    head, tail = int(0.0005 * SR), int(0.004 * SR)  # no click at either end; keep the attacks sharp
    audio[:head] *= np.linspace(0, 1, head)[:, None]
    audio[-tail:] *= np.linspace(1, 0, tail)[:, None]
    return level(audio, peak), round(peak, 4)


def write_wav(path, audio):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())


def default_dir() -> Path:
    from _env import config_path
    return config_path().parent / "sfx"


def write_kit(folder: Path) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    sounds = {}
    for name, takes in SOUNDS.items():
        sounds[name] = []
        for k, (desc, _, _) in enumerate(takes):
            audio, peak = render(name, k)
            file = f"{name}_{k + 1}.wav"
            write_wav(folder / file, audio)
            sounds[name].append({"file": file, "take": k + 1, "peak": peak,
                                 "duration": round(len(audio) / SR, 4), "what": desc})
    manifest = {"version": VERSION, "sample_rate": SR, "sounds": sounds,
                "note": "Generated by sfx.py; free to use anywhere. peak = seconds from the file's start "
                        "to the moment it was built around, the point to line up with the picture."}
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def kit(folder=None) -> dict:
    """The kit's manifest with an absolute "path" on every take, generating the files if they are
    missing or were made by another version of this script."""
    folder = Path(folder) if folder else default_dir()
    manifest = None
    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        if manifest.get("version") != VERSION or set(manifest.get("sounds", {})) != set(SOUNDS) or not all(
                (folder / t["file"]).is_file() for takes in manifest["sounds"].values() for t in takes):
            manifest = None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        manifest = None
    if manifest is None:
        manifest = write_kit(folder)
    for takes in manifest["sounds"].values():
        for t in takes:
            t["path"] = str((folder / t["file"]).resolve())
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="folder for the kit (default ~/.cappus/sfx)")
    ap.add_argument("--list", action="store_true", help="print the sounds without rewriting existing files")
    args = ap.parse_args()
    folder = Path(args.out) if args.out else default_dir()
    manifest = kit(folder) if args.list else write_kit(folder)
    if not args.list:
        for takes in manifest["sounds"].values():
            for t in takes:
                t["path"] = str((folder / t["file"]).resolve())
    print(json.dumps({"folder": str(folder.resolve()), **manifest}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

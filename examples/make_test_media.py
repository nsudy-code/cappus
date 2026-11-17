#!/usr/bin/env python3
"""Generate the synthetic clips that examples/demo.json uses (needs ffmpeg on PATH)."""
import subprocess
from pathlib import Path

out = Path(__file__).resolve().parent / "media"
out.mkdir(exist_ok=True)

jobs = {
    "landscape.mp4": ["-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=8", "-f", "lavfi", "-i", "sine=f=440:d=8",
                      "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"],
    "vertical.mp4": ["-f", "lavfi", "-i", "smptehdbars=s=1080x1920:r=30:d=6", "-f", "lavfi", "-i", "sine=f=220:d=6",
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"],
    "photo.png": ["-f", "lavfi", "-i", "color=c=0x224466:s=1600x1200:d=1", "-frames:v", "1"],
    "music.mp3": ["-f", "lavfi", "-i",
                  "aevalsrc='0.6*sin(2*PI*110*t)*exp(-8*mod(t,0.5))+0.2*sin(2*PI*880*t)*exp(-30*mod(t+0.25,0.5))':d=16",
                  "-c:a", "libmp3lame"],
}
for name, args in jobs.items():
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args, str(out / name)], check=True)
    print("wrote", out / name)

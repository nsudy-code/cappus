#!/usr/bin/env python3
"""Check that this machine is ready to make CapCut drafts, and say what to fix if it is not.

  doctor.py                  # JSON report; exit code 1 when something blocks building drafts
  doctor.py --drafts-dir D   # check a drafts folder CapCut was told to use instead of its default

Checks Python, the packages in requirements.txt, MediaInfo, ffmpeg/ffprobe, CapCut desktop and its
drafts folder, the saved CapCut plan, and the optional speech-to-text package for captions.
Standard library only, so it runs before anything is installed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from importlib import metadata, util
from pathlib import Path

from _env import capcut_install, drafts_dir_candidates, find_drafts_dir, user_tier

SKILL = Path(__file__).resolve().parent.parent
TESTED_CAPCUT = "9.8"  # the CapCut desktop version the draft format was last checked against

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def short(path) -> str:
    """A path with the home folder written as ~, for a report the user may paste somewhere.
    Commands keep full paths, so they run as printed."""
    p, home = str(path), str(Path.home())
    return "~" + p[len(home):] if p.lower().startswith(home.lower()) else p


def package(name: str, module: str):
    if util.find_spec(module) is None:
        return None
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "installed"


def tool_version(exe: str):
    path = shutil.which(exe)
    if not path:
        return None, None
    try:
        out = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=20).stdout
        return path, (out.splitlines() or [""])[0].replace(f"{exe} version ", "").split(" Copyright")[0]
    except (OSError, subprocess.SubprocessError):
        return path, None


def writable(folder: Path) -> bool:
    try:
        fd, probe = tempfile.mkstemp(prefix=".cappus-write-test-", dir=folder)
        os.close(fd)
        os.remove(probe)
        return True
    except OSError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drafts-dir", help="CapCut drafts folder to check (default: find it)")
    args = ap.parse_args()

    problems, notes = [], []
    pip = f'"{sys.executable}" -m pip install -r "{SKILL / "requirements.txt"}"'
    report = {"python": {"version": sys.version.split()[0], "executable": short(sys.executable)}}
    if sys.version_info < (3, 9):
        problems.append(f"Python {report['python']['version']} is too old; the scripts need Python 3.9 or newer.")

    pkgs = {"pycapcut": package("pycapcut", "pycapcut"), "numpy": package("numpy", "numpy"),
            "pymediainfo": package("pymediainfo", "pymediainfo"), "Pillow": package("Pillow", "PIL")}
    report["packages"] = pkgs
    missing = [n for n in ("pycapcut", "numpy") if not pkgs[n]]
    if not pkgs["Pillow"]:
        notes.append(f"Pillow is not installed, so preview.py (the preview render when CapCut cannot be "
                     f"watched) will not run. Run: {pip}")
    if missing:
        problems.append(f"{' and '.join(missing)} not installed for this Python. Run: {pip}")
    if pkgs["pymediainfo"]:
        try:
            from pymediainfo import MediaInfo
            report["mediainfo_library"] = bool(MediaInfo.can_parse())
        except Exception:
            report["mediainfo_library"] = False
        if not report["mediainfo_library"]:
            problems.append("pymediainfo is installed but cannot find the MediaInfo library, so media files "
                            "cannot be read. Install it: `sudo apt install libmediainfo0v5` (Debian/Ubuntu) "
                            "or `brew install media-info` (macOS).")

    for exe in ("ffmpeg", "ffprobe"):
        path, version = tool_version(exe)
        report[exe] = {"path": short(path), "version": version} if path else None
    if not (report["ffmpeg"] and report["ffprobe"]):
        problems.append("ffmpeg/ffprobe are not on PATH; probe.py needs them to look at the footage. Install "
                        "ffmpeg (winget install ffmpeg / brew install ffmpeg / sudo apt install ffmpeg), then "
                        "open a new terminal.")

    install = capcut_install()
    report["capcut"] = ({"installed": True, "version": install["version"], "path": short(install["path"])}
                        if install else {"installed": False})
    drafts = find_drafts_dir(args.drafts_dir)
    if drafts:
        where = next((src for p, src in drafts_dir_candidates(args.drafts_dir) if p == drafts), "")
        report["drafts_dir"] = {"path": short(drafts), "found_by": where, "writable": writable(drafts)}
        if not report["drafts_dir"]["writable"]:
            problems.append(f"CapCut's drafts folder {short(drafts)} is not writable for this user.")
    else:
        report["drafts_dir"] = None

    if args.drafts_dir and not drafts:
        problems.append(f"The drafts folder {args.drafts_dir} given with --drafts-dir does not exist. Check the "
                        "path (CapCut > Settings > Drafts location shows the one CapCut uses).")
    elif not install and not drafts:
        if sys.platform in ("win32", "darwin"):
            problems.append("CapCut desktop is not installed (no app and no drafts folder found). The drafts this "
                            "skill makes open only in CapCut desktop (capcut.com/download). Without it, offer "
                            "to render an MP4 with ffmpeg instead.")
        else:
            problems.append("CapCut desktop runs on Windows and macOS only, so drafts made here must be copied "
                            "to a computer that has it. If the user has none, offer to render an MP4 with "
                            "ffmpeg instead.")
    elif not drafts:
        problems.append("CapCut is installed but its drafts folder was not found. Open CapCut once and create "
                        "a project so it makes the folder. If the drafts location was changed (CapCut > "
                        "Settings > Drafts location), set CAPCUT_DRAFTS to that folder or pass --drafts-dir.")
    elif not install:
        notes.append("Found a CapCut drafts folder but not the app itself; it may be installed somewhere "
                     "unusual. The user opens the drafts in CapCut desktop.")
    if install and install["version"] and install["version"].split(".")[:2] != TESTED_CAPCUT.split("."):
        notes.append(f"CapCut {install['version']}: the draft format was last checked against CapCut "
                     f"{TESTED_CAPCUT}. If a draft does not open, ask the user to update CapCut.")

    tier, source = user_tier()
    report["plan"] = {"tier": tier, "source": short(source) if os.sep in source else source}
    if tier is None:
        notes.append("CapCut plan not saved yet: ask the user once whether they have CapCut Pro, then run "
                      "tier.py pro or tier.py free.")

    report["captions_from_speech"] = package("faster-whisper", "faster_whisper")
    if not report["captions_from_speech"]:
        notes.append("Optional: captions from speech need faster-whisper: "
                     f'"{sys.executable}" -m pip install -r "{SKILL / "requirements-captions.txt"}"')

    report["face_detection"] = package("opencv-python-headless", "cv2")
    if report["face_detection"] and report["face_detection"].split(".")[0] not in ("4", "installed"):
        report["face_detection"] = None  # OpenCV 5 dropped the face cascades faces.py uses
    if not report["face_detection"]:
        notes.append("Optional: framing talking heads on the face (faces.py, used by cut_talk.py) needs "
                     f'OpenCV 4: "{sys.executable}" -m pip install -r "{SKILL / "requirements-faces.txt"}"')

    report["website_capture"] = package("playwright", "playwright")
    if not report["website_capture"]:
        notes.append("Optional: capturing a website for a promo (site_capture.py) needs Playwright: "
                     f'"{sys.executable}" -m pip install -r "{SKILL / "requirements-web.txt"}", then '
                     f'"{sys.executable}" -m playwright install chromium')

    report["ready"] = not problems
    report["problems"] = problems
    report["notes"] = notes
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())

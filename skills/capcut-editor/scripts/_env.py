"""This user's saved settings and where CapCut lives on this machine.

Standard library only, so doctor.py can use it before the requirements are installed.
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import sys
from pathlib import Path


def config_path() -> Path:
    return Path(os.environ.get("CAPPUS_CONFIG") or (Path.home() / ".cappus" / "config.json"))


def load_config() -> dict:
    try:
        with open(config_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(cfg: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


def user_tier():
    """Return (tier, source): tier is "pro", "free" or None when nobody has said yet."""
    env = (os.environ.get("CAPPUS_TIER") or "").strip().lower()
    if env in ("pro", "free"):
        return env, "CAPPUS_TIER environment variable"
    saved = load_config().get("tier")
    if saved in ("pro", "free"):
        return saved, str(config_path())
    return None, "not set"


def backups_dir() -> Path:
    return config_path().parent / "backups"


def drafts_dir_candidates(explicit=None) -> list:
    """(path, where the path came from) for every place CapCut's drafts folder may be, in order."""
    out = []
    if explicit:
        out.append((Path(explicit), "--drafts-dir"))
    if os.environ.get("CAPCUT_DRAFTS"):
        out.append((Path(os.environ["CAPCUT_DRAFTS"]), "CAPCUT_DRAFTS environment variable"))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        out.append((Path(local) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft", "CapCut default"))
    home = Path.home()
    out.append((home / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft", "CapCut default"))
    out.append((home / "AppData" / "Local" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft",
                "CapCut default"))
    return out


def find_drafts_dir(explicit=None):
    """Locate CapCut's draft folder. Returns a Path or None.

    An explicit folder (--drafts-dir) is the only candidate: if it does not exist the result is None,
    never one of the defaults, so a typo or a scratch folder cannot send drafts into the real CapCut folder."""
    if explicit:
        path = Path(explicit)
        return path if path.is_dir() else None
    for path, _ in drafts_dir_candidates():
        if path.is_dir():
            return path
    return None


def draft_folder(arg: str, drafts):
    """The draft folder that a command-line argument means, or None.

    A bare name is a draft in CapCut's drafts folder, even when the current folder has a folder of the
    same name (the agent usually works in the user's project folder, which is often named like the draft).
    Anything that looks like a path (absolute, or containing a slash) is taken as a path first."""
    path = Path(arg)
    named = drafts / arg if drafts is not None and arg not in (".", "..") else None
    looks_like_path = path.is_absolute() or "/" in arg or "\\" in arg
    order = [path, named] if looks_like_path else [named, path]
    return next((p for p in order if p is not None and p.is_dir()), None)


def capcut_install():
    """Where CapCut desktop is installed and its version: {"path", "version"}, or None if not found."""
    if sys.platform == "win32":
        apps = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "CapCut" / "Apps"
        if not (apps / "CapCut.exe").is_file():
            return None
        version = None
        try:
            m = re.search(r'full_appver\s+value="([^"]+)"', (apps / "ProductInfo.xml").read_text(encoding="utf-8-sig"))
            version = m.group(1) if m else None
        except OSError:
            pass
        if not version:  # each version has its own folder, e.g. Apps/9.8.0.4213
            found = [p.name for p in apps.iterdir() if p.is_dir() and re.fullmatch(r"\d+(\.\d+){2,3}", p.name)]
            version = max(found, key=lambda v: [int(x) for x in v.split(".")], default=None)
        return {"path": str(apps), "version": version}
    if sys.platform == "darwin":
        for app in (Path("/Applications/CapCut.app"), Path.home() / "Applications" / "CapCut.app"):
            if app.is_dir():
                try:
                    with open(app / "Contents" / "Info.plist", "rb") as f:
                        version = plistlib.load(f).get("CFBundleShortVersionString")
                except (OSError, ValueError):
                    version = None
                return {"path": str(app), "version": version}
    return None

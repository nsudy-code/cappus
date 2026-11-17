import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "capcut-editor"
SCRIPTS = SKILL / "scripts"
EXAMPLES = ROOT / "examples"
MEDIA = EXAMPLES / "media"

sys.path.insert(0, str(SCRIPTS))


def run(script, *args, cwd=None):
    """Run a bundled script the way Claude does and return the CompletedProcess."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], cwd=cwd, env=env,
                          capture_output=True, text=True, encoding="utf-8")


@pytest.fixture(scope="session")
def media():
    """The synthetic clips examples/demo.json uses (made with ffmpeg on first use)."""
    need = ("landscape.mp4", "vertical.mp4", "photo.png", "music.mp3")
    if not all((MEDIA / n).is_file() for n in need):
        subprocess.run([sys.executable, str(EXAMPLES / "make_test_media.py")], check=True)
    return MEDIA


@pytest.fixture(autouse=True)
def cappus_home(tmp_path, monkeypatch):
    """Keep the user's ~/.cappus (plan, backups) out of every test."""
    cfg = tmp_path / "cappus-home" / "config.json"
    monkeypatch.setenv("CAPPUS_CONFIG", str(cfg))
    monkeypatch.delenv("CAPPUS_TIER", raising=False)
    monkeypatch.delenv("CAPCUT_DRAFTS", raising=False)
    return cfg.parent

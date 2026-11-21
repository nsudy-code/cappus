"""preview.py draws text in the font CapCut uses: its cached download, its default, or a stand-in."""
import shutil
from pathlib import Path

import pycapcut as cc
import pytest
from PIL import ImageFont

import preview


def any_ttf() -> Path:
    for name in preview.FONT_FILES:
        try:
            return Path(ImageFont.truetype(name, 10).path)
        except OSError:
            continue
    pytest.skip("no TrueType font on this machine")


@pytest.fixture
def capcut(tmp_path, monkeypatch):
    """A fake CapCut: a User Data folder with one cached font, an install with the default font."""
    data, inst = tmp_path / "User Data", tmp_path / "CapCut" / "9.8.0"
    src = any_ttf()
    poppins = cc.FontType.Poppins_Bold.value
    cached = data / "Cache" / "effect" / "149842157" / poppins.md5
    cached.mkdir(parents=True)
    shutil.copy(src, cached / "readme.ttf")             # another file in the folder: not the one
    shutil.copy(src, cached / "Poppins-Bold.ttf")
    sysfont = inst / "Resources" / "Font" / "SystemFont"
    sysfont.mkdir(parents=True)
    shutil.copy(src, sysfont / "CapCutSansText-Bold.otf")
    monkeypatch.setattr(preview, "_capcut_dirs", lambda: ([data], [inst]))
    monkeypatch.setattr(preview, "_font_paths", {})
    return data, inst


def test_finds_a_downloaded_font_by_its_md5(capcut):
    path, where = preview.font_file(cc.FontType.Poppins_Bold)
    assert Path(path).name == "Poppins-Bold.ttf" and where == "CapCut's cache"


def test_text_with_no_font_uses_capcut_sans(capcut):
    path, where = preview.font_file(None, bold=True)
    assert Path(path).name == "CapCutSansText-Bold.otf" and where == "CapCut default font"


def test_a_font_capcut_has_not_downloaded_falls_back(capcut, monkeypatch):
    monkeypatch.setenv("WINDIR", str(capcut[0] / "nowhere"))
    monkeypatch.setenv("LOCALAPPDATA", str(capcut[0] / "nowhere"))
    monkeypatch.setattr(Path, "home", lambda: capcut[0] / "nowhere")
    assert preview.font_file(cc.FontType.Anton) == (None, None)


def test_render_reports_real_and_stand_in_fonts(capcut, tmp_path, monkeypatch):
    import json
    import subprocess
    monkeypatch.setattr(Path, "home", lambda: capcut[0] / "nowhere")
    monkeypatch.setenv("WINDIR", str(capcut[0] / "nowhere"))
    monkeypatch.setenv("LOCALAPPDATA", str(capcut[0] / "nowhere"))
    img = tmp_path / "sq.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1",
                    "-frames:v", "1", str(img)], check=True)
    spec = tmp_path / "s.json"
    spec.write_text(json.dumps({"name": "fonts", "video": [{"src": str(img), "duration": 1}], "texts": [
        {"text": "Real", "at": 0, "end": 1, "font": "Poppins_Bold"},
        {"text": "Stand", "at": 0, "end": 1, "y": 0.4, "font": "Anton"},
        {"text": "Plain", "at": 0, "end": 1, "y": -0.4, "bold": True}]}), encoding="utf-8")
    rep = preview.render(spec, tmp_path / "pv", size=320, fps=5)
    assert rep["fonts"] == {"Poppins-Bold": "CapCut's cache", "Anton": "stand-in",
                            "CapCut Sans": "CapCut default font"}
    assert any("font Anton" in s for s in rep["not_drawn"])
    assert not any("Poppins" in s for s in rep["not_drawn"])

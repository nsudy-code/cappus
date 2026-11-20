"""An explicit --drafts-dir is always the folder used: never one of CapCut's defaults instead."""
import json

from conftest import run
from _env import find_drafts_dir


def test_missing_explicit_folder_does_not_fall_back(tmp_path, monkeypatch):
    decoy = tmp_path / "real-capcut-drafts"
    decoy.mkdir()
    monkeypatch.setenv("CAPCUT_DRAFTS", str(decoy))
    assert find_drafts_dir(tmp_path / "missing") is None
    assert find_drafts_dir() == decoy


def test_build_creates_missing_drafts_dir(tmp_path, monkeypatch, media):
    decoy = tmp_path / "real-capcut-drafts"  # stands in for CapCut's own folder, which must stay untouched
    decoy.mkdir()
    monkeypatch.setenv("CAPCUT_DRAFTS", str(decoy))
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"name": "dd-draft", "video": [{"src": str(media / "photo.png"), "duration": 2}]}),
                    encoding="utf-8")
    drafts = tmp_path / "scratch" / "drafts"  # does not exist yet
    res = run("build_draft.py", spec, "--drafts-dir", drafts)
    assert res.returncode == 0, res.stderr
    assert (drafts / "dd-draft" / "draft_info.json").is_file()
    assert list(decoy.iterdir()) == []


def test_inspect_and_doctor_report_missing_drafts_dir(tmp_path, monkeypatch):
    decoy = tmp_path / "real-capcut-drafts"
    decoy.mkdir()
    monkeypatch.setenv("CAPCUT_DRAFTS", str(decoy))
    missing = tmp_path / "missing"
    res = run("inspect_draft.py", "--list", "--drafts-dir", missing)
    assert res.returncode == 2 and "does not exist" in res.stderr
    res = run("doctor.py", "--drafts-dir", missing)
    assert "does not exist" in res.stdout + res.stderr

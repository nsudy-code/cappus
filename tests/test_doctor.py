"""doctor.py reports what is ready and what to fix, and runs before anything is installed."""
import json
import os
import subprocess
import sys

from conftest import SCRIPTS, run


def test_doctor_finds_the_drafts_folder_it_is_given(tmp_path, monkeypatch):
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    monkeypatch.setenv("CAPCUT_DRAFTS", str(drafts))
    res = run("doctor.py")
    report = json.loads(res.stdout)
    assert res.returncode == (0 if report["ready"] else 1), report["problems"]
    assert report["drafts_dir"]["found_by"] == "CAPCUT_DRAFTS environment variable"
    assert report["drafts_dir"]["writable"] is True
    assert report["packages"]["pycapcut"], "the test environment has the requirements installed"
    assert not list(drafts.iterdir()), "the write test leaves nothing behind"


def test_doctor_without_the_requirements_says_how_to_install_them(tmp_path):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", CAPPUS_CONFIG=str(tmp_path / "config.json"))
    res = subprocess.run([sys.executable, "-S", str(SCRIPTS / "doctor.py")], env=env,  # -S: no site-packages
                         capture_output=True, text=True, encoding="utf-8")
    assert "Traceback" not in res.stderr, res.stderr
    report = json.loads(res.stdout)
    assert res.returncode == 1 and report["ready"] is False
    assert report["packages"]["pycapcut"] is None
    assert any("pip install -r" in p and "requirements.txt" in p for p in report["problems"]), report["problems"]
    assert report["plan"]["tier"] is None

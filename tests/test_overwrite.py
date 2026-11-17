"""Rebuilding a draft must never lose what the user changed in CapCut."""
import json
import os
import re
import time
import uuid

import pytest

from conftest import run
from _common import BUILD_FILE, edit_check

UUID = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")


@pytest.fixture
def built(tmp_path, media):
    """A draft built into a throwaway drafts folder; returns (spec path, drafts folder, draft folder)."""
    spec = {"name": "t-draft", "video": [{"src": str(media / "vertical.mp4"), "duration": 3, "id": "a",
                                          "transition": "dissolve"},
                                         {"src": str(media / "photo.png"), "duration": 2}],
            "audio": [{"src": str(media / "music.mp3"), "volume": 0.6, "fade": {"in": 0.5, "out": 1}}],
            "texts": [{"text": "Hello", "at": 0.5, "duration": 2, "size": 10}]}
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    res = run("build_draft.py", spec_path, "--drafts-dir", drafts)
    assert res.returncode == 0, res.stderr
    return spec_path, drafts, drafts / "t-draft"


def rebuild(spec_path, drafts, *flags):
    return run("build_draft.py", spec_path, "--drafts-dir", drafts, *flags)


def resave(folder, change=None):
    """Write the timeline back the way CapCut does on open: new ids, a newer draft_content.json."""
    text = (folder / "draft_info.json").read_text(encoding="utf-8")
    fresh = {}
    text = UUID.sub(lambda m: fresh.setdefault(m.group(0), str(uuid.uuid4()).upper()), text)
    data = json.loads(text)
    data["materials"].setdefault("speeds", []).append({"id": "x-speed", "speed": 1.0, "type": "speed"})
    if change:
        change(data)
    target = folder / "draft_content.json"
    target.write_text(json.dumps(data), encoding="utf-8")
    later = time.time() + 60
    os.utime(target, (later, later))


def video_segments(data):
    return next(t for t in data["tracks"] if t["type"] == "video")["segments"]


def test_build_writes_the_fingerprint(built):
    _, _, folder = built
    saved = json.loads((folder / BUILD_FILE).read_text(encoding="utf-8"))
    assert len(saved["signature_sha256"]) == 64
    assert edit_check(folder)["edited"] is False


def test_capcut_resave_is_not_an_edit(built):
    _, _, folder = built
    resave(folder)
    assert edit_check(folder)["edited"] is False


def remeasure_music(data, extra=27_666):
    """CapCut 9.8 measured a 16.039 s MP3 as 16.067 s on open and stretched the clip that plays it."""
    for m in data["materials"]["audios"]:
        m["duration"] += extra
    for t in data["tracks"]:
        if t["type"] == "audio":
            for s in t["segments"]:
                s["target_timerange"]["duration"] += extra
                s["source_timerange"]["duration"] += extra


def test_capcut_remeasuring_media_is_not_an_edit(built):
    _, _, folder = built
    resave(folder, remeasure_music)
    assert edit_check(folder)["edited"] is False


def test_small_shift_after_a_stretched_clip_is_not_an_edit(built):
    def shift(data):
        segs = video_segments(data)
        segs[0]["target_timerange"]["duration"] += 30_000
        segs[1]["target_timerange"]["start"] += 30_000
    _, _, folder = built
    resave(folder, shift)
    assert edit_check(folder)["edited"] is False


def test_unchanged_draft_is_replaced_and_backed_up(built, cappus_home):
    spec_path, drafts, folder = built
    resave(folder)
    res = rebuild(spec_path, drafts, "--overwrite")
    assert res.returncode == 0, res.stderr
    assert "previous_version" in json.loads(res.stdout)
    backups = list((cappus_home / "backups").iterdir())
    assert [b.name.startswith("t-draft-") for b in backups] == [True]


def test_rebuild_without_a_flag_is_refused(built):
    spec_path, drafts, _ = built
    res = rebuild(spec_path, drafts)
    assert res.returncode != 0 and "--overwrite" in res.stderr


@pytest.mark.parametrize("what, change", [
    ("volume", lambda d: video_segments(d)[0].update(volume=0.3)),
    ("trim", lambda d: video_segments(d)[0]["target_timerange"].update(duration=2_000_000)),
    ("clip removed", lambda d: video_segments(d).pop()),
])
def test_edit_in_capcut_blocks_overwrite(built, cappus_home, what, change):
    spec_path, drafts, folder = built
    resave(folder, change)
    state = edit_check(folder)
    assert state["edited"] is True, what
    assert state.get("changes"), what

    res = rebuild(spec_path, drafts, "--overwrite")
    assert res.returncode != 0
    assert "was changed in CapCut" in res.stderr and "--force" in res.stderr
    assert (folder / "draft_content.json").is_file(), "the edited draft must be left alone"

    res = rebuild(spec_path, drafts, "--force")
    assert res.returncode == 0, res.stderr
    backup = next((cappus_home / "backups").iterdir())
    assert json.loads((backup / "draft_content.json").read_text(encoding="utf-8")) != {}
    assert edit_check(folder)["edited"] is False


def test_backups_keep_the_newest_five(built, cappus_home):
    spec_path, drafts, _ = built
    made = []
    for _ in range(7):
        res = rebuild(spec_path, drafts, "--force")
        assert res.returncode == 0, res.stderr
        made.append(json.loads(res.stdout)["previous_version"].split(" (")[0].split("moved to ")[-1])
    kept = sorted(p.name for p in (cappus_home / "backups").iterdir())
    assert kept == sorted(os.path.basename(p) for p in made[-5:])


def test_draft_from_an_older_cappus_falls_back_to_file_times(built):
    _, _, folder = built
    (folder / BUILD_FILE).unlink()
    assert edit_check(folder)["edited"] is False
    resave(folder)
    state = edit_check(folder)
    assert state["edited"] is True and "file times" in state["how"]

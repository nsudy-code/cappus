"""Rebuilding a draft must never lose what the user changed in CapCut."""
import errno
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import pytest

import build_draft
import _common
from conftest import run
from _common import BUILD_FILE, edit_check, newest_timeline

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


def attach(kind, material):
    """Attach an audio-tool material to every audio clip, the way CapCut stores it."""
    def change(data):
        for n, t in enumerate(x for x in data["tracks"] if x["type"] == "audio"):
            for s in t["segments"]:
                mid = f"{kind}-{n}-{s['id']}"
                data["materials"].setdefault(kind, []).append({"id": mid, **material})
                s.setdefault("extra_material_refs", []).append(mid)
    return change


OFF_TOOLS = {  # what CapCut 9.8 attaches to every clip when it saves a draft
    "loudnesses": {"enable": False, "time_range": None, "file_id": "", "target_loudness": 0.0, "loudness_param": None},
    "vocal_separations": {"type": "vocal_separation", "choice": 0, "removed_sounds": [], "time_range": None,
                          "production_path": "", "final_algorithm": "", "enter_from": ""},
    "sound_channel_mappings": {"type": "none", "audio_channel_mapping": 0, "is_config_open": False},
    "realtime_denoises": {"is_denoise": False, "denoise_mode": 0.0, "denoise_rate": 0.0},
    "beats": {"user_beats": [], "enable_ai_beats": False, "ai_beats": None},
}


@pytest.mark.parametrize("kind", sorted(OFF_TOOLS))
def test_audio_tools_left_off_are_not_an_edit(built, kind):
    _, _, folder = built
    resave(folder, attach(kind, OFF_TOOLS[kind]))
    assert edit_check(folder)["edited"] is False


@pytest.mark.parametrize("kind, on", [
    ("realtime_denoises", {"is_denoise": True, "denoise_mode": 1.0, "denoise_rate": 0.5}),
    ("loudnesses", {"enable": True, "target_loudness": -14.0}),
    ("vocal_separations", {"choice": 1}),
    ("sound_channel_mappings", {"type": "left", "audio_channel_mapping": 1}),
    ("beats", {"user_beats": [1_000_000, 2_000_000]}),
    ("beats", {"enable_ai_beats": True}),
])
def test_audio_tool_turned_on_is_an_edit(built, kind, on):
    """Reduce noise, Normalize loudness, Isolate voice, channels and beat markers are the user's work."""
    _, _, folder = built
    resave(folder, attach(kind, {**OFF_TOOLS[kind], **on}))
    state = edit_check(folder)
    assert state["edited"] is True, kind
    assert any("audio tools" in c for c in state["changes"]), state


def test_unchanged_draft_is_replaced_and_backed_up(built, cappus_home):
    spec_path, drafts, folder = built
    resave(folder)
    res = rebuild(spec_path, drafts, "--overwrite")
    assert res.returncode == 0, res.stderr
    assert "previous_version" in json.loads(res.stdout)
    backups = list((cappus_home / "backups").iterdir())
    assert [b.name.startswith("t-draft-") for b in backups] == [True]
    assert not (drafts.parent / build_draft.STAGING).exists(), "the staging folder is removed once empty"


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


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def empty(folder):
    return not folder.exists() or not any(folder.iterdir())


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows refuses to rename a folder with a file open in it")
@pytest.mark.parametrize("flag", ["--overwrite", "--force"])
def test_open_file_leaves_the_draft_untouched(built, cappus_home, flag):
    """CapCut, OneDrive, an antivirus scan or the search indexer can hold a file in the draft open."""
    spec_path, drafts, folder = built
    before = snapshot(folder)
    with open(folder / "draft_meta_info.json", "rb"):
        res = rebuild(spec_path, drafts, flag)
    assert res.returncode != 0
    assert "nothing was changed" in res.stderr
    assert snapshot(folder) == before
    assert empty(cappus_home / "backups")
    assert empty(drafts.parent / build_draft.STAGING)
    res = rebuild(spec_path, drafts, flag)  # once the file is closed, the rebuild goes through
    assert res.returncode == 0, res.stderr


def test_backup_on_another_drive_is_copied_without_masks(built, cappus_home, monkeypatch):
    _, _, folder = built
    (folder / "matting").mkdir()
    (folder / "matting" / "mask.bin").write_bytes(b"mask")
    before = snapshot(folder)
    staged = build_draft.stage_out(folder, "t-draft")
    assert not folder.exists() and snapshot(staged) == before

    real = os.rename

    def rename(src, dst):
        if Path(dst).is_relative_to(cappus_home):
            raise OSError(errno.EXDEV, "The system cannot move the file to a different disk drive")
        real(src, dst)
    monkeypatch.setattr(os, "rename", rename)
    note = build_draft.back_up(staged, "t-draft")
    assert note.startswith("moved to "), note
    backup = Path(note.split(" (")[0][len("moved to "):])
    assert snapshot(backup) == {k: v for k, v in before.items() if not k.startswith("matting/")}
    assert not staged.parent.exists()


def test_failed_backup_keeps_the_old_draft_where_it_was_staged(built, monkeypatch):
    _, _, folder = built
    before = snapshot(folder)
    staged = build_draft.stage_out(folder, "t-draft")

    def fail(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(os, "rename", fail)
    monkeypatch.setattr(build_draft.shutil, "copytree", fail)
    note = build_draft.back_up(staged, "t-draft")
    assert note.startswith(f"kept at {staged}"), note
    assert snapshot(staged) == before


def test_staging_cleanup_removes_only_copied_leftovers(tmp_path):
    drafts, root = tmp_path / "drafts", tmp_path / build_draft.STAGING
    only_copy = root / "a-20260101-000000" / "a"
    only_copy.mkdir(parents=True)
    (only_copy / "draft_info.json").write_text("{}")
    leftover = root / "b-20260101-000000" / "b"
    leftover.mkdir(parents=True)
    (leftover / "in-use.bin").write_bytes(b"x")
    (leftover.parent / build_draft.COPIED).touch()
    (drafts / "c").mkdir(parents=True)
    build_draft.stage_out(drafts / "c", "c")
    assert only_copy.is_dir()
    assert not leftover.parent.exists()


def test_failed_write_puts_the_old_draft_back(built, cappus_home, monkeypatch):
    spec_path, drafts, folder = built
    before = snapshot(folder)
    spec_text = spec_path.read_text(encoding="utf-8")
    builder = build_draft.Builder(json.loads(spec_text), spec_path.parent)
    builder.build()
    real = Path.write_text

    def write_text(self, *args, **kwargs):
        if self.name == "draft_meta_info.json":
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(self, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", write_text)
    with pytest.raises(build_draft.SpecError, match="nothing was changed"):
        build_draft.write_draft(builder, drafts, "t-draft", True, spec_text)
    assert snapshot(folder) == before
    assert empty(drafts.parent / build_draft.STAGING)
    assert empty(cappus_home / "backups")


def open_in_capcut(folder, main=None, name="Timeline 01", timelines=None):
    """Convert the draft the way CapCut 9 does the first time it opens one: Timelines/project.json names
    the main timeline, and Timelines/<id>/ holds its files."""
    data = json.loads((folder / "draft_info.json").read_text(encoding="utf-8"))
    main = main or data["id"]
    (folder / "Timelines" / main).mkdir(parents=True)
    for n in ("draft_content.json", "draft_info.json"):
        (folder / "Timelines" / main / n).write_text(json.dumps(data), encoding="utf-8")
    entry = {"create_time": 1, "id": main, "is_marked_delete": False, "name": name, "update_time": 1}
    (folder / "Timelines" / "project.json").write_text(json.dumps({
        "config": {"color_space": 0, "hdr_vivid": False}, "create_time": 1, "id": main, "main_timeline_id": main,
        "timelines": timelines or [entry], "update_time": 1, "version": 0}), encoding="utf-8")
    return main


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_rebuild_keeps_the_timelines_layout_capcut_made(built):
    """CapCut 9.8 kept running would not open a replacement draft without Timelines/ until a restart."""
    spec_path, drafts, folder = built
    main = open_in_capcut(folder, name="My cut")
    res = rebuild(spec_path, drafts, "--overwrite")
    assert res.returncode == 0, res.stderr
    project = read(folder / "Timelines" / "project.json")
    assert project["main_timeline_id"] == project["id"] == main
    assert [(t["id"], t["name"], t["is_marked_delete"]) for t in project["timelines"]] == [(main, "My cut", False)]
    assert project["config"] == {"color_space": 0, "hdr_vivid": False}
    root = (folder / "draft_content.json").read_text(encoding="utf-8")
    for n in ("draft_content.json", "draft_info.json"):
        assert (folder / "Timelines" / main / n).read_text(encoding="utf-8") == root
    assert read(folder / "draft_content.json")["id"] == main
    assert edit_check(folder)["edited"] is False
    res = rebuild(spec_path, drafts, "--overwrite")  # and again, over the layout it wrote itself
    assert res.returncode == 0, res.stderr
    assert read(folder / "Timelines" / "project.json")["main_timeline_id"] == main


def test_rebuild_uses_the_main_timeline_id_capcut_chose(built):
    spec_path, drafts, folder = built
    other = {"create_time": 1, "id": "SECOND-1", "is_marked_delete": False, "name": "Timeline 02", "update_time": 1}
    main = open_in_capcut(folder, main="ABCD-1234", timelines=[
        {"create_time": 1, "id": "ABCD-1234", "is_marked_delete": False, "name": "Timeline 01", "update_time": 1}, other])
    res = rebuild(spec_path, drafts, "--overwrite")
    assert res.returncode == 0, res.stderr
    assert read(folder / "draft_content.json")["id"] == main
    assert read(folder / "Timelines" / main / "draft_info.json")["id"] == main
    assert [t["id"] for t in read(folder / "Timelines" / "project.json")["timelines"]] == [main]
    assert sorted(p.name for p in (folder / "Timelines").iterdir()) == [main, "project.json"]


def test_draft_never_opened_in_capcut_gets_no_timelines(built):
    spec_path, drafts, folder = built
    assert not (folder / "Timelines").exists()
    res = rebuild(spec_path, drafts, "--overwrite")
    assert res.returncode == 0, res.stderr
    assert not (folder / "Timelines").exists()


@pytest.mark.parametrize("project", [
    "not json", "[]", "{}", '{"main_timeline_id": 5}', '{"main_timeline_id": "../../escape"}',
    '{"main_timeline_id": ""}', '{"main_timeline_id": "ok-1", "timelines": "x"}',
])
def test_unreadable_project_json_is_left_behind(built, project):
    spec_path, drafts, folder = built
    (folder / "Timelines").mkdir()
    (folder / "Timelines" / "project.json").write_text(project, encoding="utf-8")
    res = rebuild(spec_path, drafts, "--overwrite")
    assert res.returncode == 0, res.stderr
    files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
    if project.startswith('{"main_timeline_id": "ok-1"'):
        assert "Timelines/ok-1/draft_info.json" in files
    else:
        assert not (folder / "Timelines").exists(), files
    assert not (drafts / "escape").exists() and not (drafts.parent / "escape").exists()


# A keyframe value on a 4-decimal rounding boundary, as eased keyframes often produce:
# -0.23 + 0.03 * 0.875 is -0.20375000000000001, which rounds to -0.2038, while CapCut's -0.20375 rounds to -0.2037.
BOUNDARY = -0.23 + 0.03 * 0.875


@pytest.fixture
def keyframed(tmp_path, media):
    spec = {"name": "t-kf", "video": [{"src": str(media / "vertical.mp4"), "duration": 3,
                                       "keyframes": {"y": [[0, -0.23], [0.3, BOUNDARY]]}}]}
    spec_path = tmp_path / "kf.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    res = run("build_draft.py", spec_path, "--drafts-dir", drafts)
    assert res.returncode == 0, res.stderr
    return drafts / "t-kf"


def six_decimals(data):
    """CapCut 9.7.1 saves keyframe values with 6 decimals."""
    for t in data["tracks"]:
        for s in t["segments"]:
            for k in s.get("common_keyframes") or []:
                for kf in k["keyframe_list"]:
                    kf["values"] = [round(v, 6) for v in kf["values"]]


def test_capcut_saving_six_decimals_is_not_an_edit(keyframed):
    """Seen with CapCut 9.7.1: a draft that was only opened and closed read as "keyframes changed"."""
    resave(keyframed, six_decimals)
    state = edit_check(keyframed)
    assert state["edited"] is False, state


def old_round(value, nd=4):
    """How cappus 0.5.2 and older rounded the signature."""
    try:
        return round(float(value), nd)
    except (TypeError, ValueError):
        return None


def test_fingerprint_stored_by_an_older_cappus_still_matches(keyframed):
    data = json.loads((keyframed / "draft_info.json").read_text(encoding="utf-8"))
    real = _common._r
    _common._r = old_round
    try:
        old = _common.timeline_signature(data)
    finally:
        _common._r = real
    (keyframed / BUILD_FILE).write_text(json.dumps({"signature_sha256": _common.signature_hash(old),
                                                    "signature": old}), encoding="utf-8")
    resave(keyframed, six_decimals)
    _, now = newest_timeline(keyframed)
    assert _common.signature_hash(_common.timeline_signature(now)) != _common.signature_hash(old), \
        "the stored signature must differ, so this exercises the value tolerance"
    state = edit_check(keyframed)
    assert state["edited"] is False, state


def test_small_real_keyframe_edit_is_still_an_edit(keyframed):
    def nudge(data):
        six_decimals(data)
        kf = video_segments(data)[0]["common_keyframes"][0]["keyframe_list"][-1]
        kf["values"] = [kf["values"][0] + 0.01]  # about 10 px on a 1920 px tall canvas
    resave(keyframed, nudge)
    state = edit_check(keyframed)
    assert state["edited"] is True and any("keyframes" in c for c in state["changes"]), state


def lower_volume(data):
    video_segments(data)[0]["volume"] = 0.3


def test_edit_counts_whatever_the_file_times(built):
    """CapCut 9.7.1 saves an edit to draft_content.json only. Once a copy, sync or restore resets the
    file times, the untouched draft_info.json can be the newest file."""
    _, _, folder = built
    resave(folder, lower_volume)
    later = time.time() + 600
    os.utime(folder / "draft_info.json", (later, later))
    state = edit_check(folder)
    assert state["edited"] is True and any("volume" in c for c in state["changes"]), state


def test_capcut_9_main_timeline_is_the_live_one(built):
    """After CapCut 9.7.1 opens a draft, both draft_info.json files stay as they were at that moment;
    edits go to draft_content.json at the top level and in Timelines/<main id>/."""
    _, _, folder = built
    main = open_in_capcut(folder)
    data = read(folder / "draft_info.json")
    lower_volume(data)
    for p in (folder / "draft_content.json", folder / "Timelines" / main / "draft_content.json"):
        p.write_text(json.dumps(data), encoding="utf-8")
    stale = time.time() + 600
    for p in (folder / "draft_info.json", folder / "Timelines" / main / "draft_info.json"):
        os.utime(p, (stale, stale))  # newest by file time, but not the timeline CapCut reads
    path, _ = newest_timeline(folder)
    assert path == folder / "Timelines" / main / "draft_content.json"
    assert edit_check(folder)["edited"] is True

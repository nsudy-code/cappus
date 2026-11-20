"""sfx.py makes the kit; build_draft.py places each sound so its peak lands one frame after its picture."""
import json
import wave
from pathlib import Path

import numpy as np
import pytest

import sfx
from build_draft import Builder
from conftest import EXAMPLES, run


def read_wav(path):
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (2, 2, sfx.SR)
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 2) / 32767


def test_kit_has_every_sound_with_its_peak(tmp_path):
    kit = sfx.kit(tmp_path / "kit")["sounds"]
    assert {n: len(t) for n, t in kit.items()} == {"whoosh": 3, "pop": 2, "tick": 2, "hit": 2, "riser": 1}
    for name, takes in kit.items():
        for t in takes:
            audio = read_wav(t["path"])
            assert abs(len(audio) / sfx.SR - t["duration"]) < 0.001
            assert 0 <= t["peak"] < t["duration"]
            peak = np.abs(audio).max()
            assert 0.2 < peak <= sfx.CEILING + 0.001, (t["file"], peak)
            i = int(t["peak"] * sfx.SR)  # the sound is loud at its peak, not silent
            assert np.abs(audio[max(0, i - 441): i + 441]).max() > 0.3 * peak, t["file"]
            assert np.abs(audio[0]).max() < 0.01 and np.abs(audio[-1]).max() < 0.01, t["file"]  # no clicks
    assert kit["riser"][0]["peak"] > 1.9  # a riser peaks at its end
    assert all(t["peak"] < 0.01 for n in ("pop", "tick", "hit") for t in kit[n])  # attacks peak at once


def test_whoosh_takes_differ_and_rebuilds_are_identical(tmp_path):
    a = sfx.kit(tmp_path / "a")["sounds"]["whoosh"]
    b = sfx.kit(tmp_path / "b")["sounds"]["whoosh"]
    assert len({t["duration"] for t in a}) == 3
    for x, y in zip(a, b):
        assert np.array_equal(read_wav(x["path"]), read_wav(y["path"]))


def test_kit_regenerates_when_stale(tmp_path):
    folder = tmp_path / "kit"
    sfx.kit(folder)
    manifest = json.loads((folder / sfx.MANIFEST).read_text(encoding="utf-8"))
    manifest["version"] = 0
    (folder / sfx.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "pop_1.wav").unlink()
    sfx.kit(folder)
    assert (folder / "pop_1.wav").is_file()
    assert json.loads((folder / sfx.MANIFEST).read_text(encoding="utf-8"))["version"] == sfx.VERSION


def test_cli_lists_the_kit(tmp_path):
    res = run("sfx.py", "--out", tmp_path / "kit")
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["sounds"]["whoosh"][0]["file"] == "whoosh_1.wav"


def test_demo_sfx_spec_validates(media):
    res = run("build_draft.py", EXAMPLES / "demo-sfx.json", "--check")
    assert res.returncode == 0, res.stderr
    report = json.loads(res.stdout)
    assert report["status"].startswith("valid")
    assert not report["warnings"]
    assert any(t.startswith("audio:sfx") for t in report["tracks"])


def build(media, fps=30, clips=3, **sections):
    spec = {"name": "sfx", "fps": fps,
            "video": [{"id": f"c{k}", "src": str(media / "vertical.mp4"), "duration": 2} for k in range(clips)]}
    spec.update(sections)
    b = Builder(spec, media.parent, allow_pro=False)
    b.build()
    return b


def sfx_segments(b):
    """(file name, start s, source in s, duration s, volume) of every sound, in time order."""
    out = []
    for track in b.script.tracks.values():
        if track.name.startswith("sfx"):
            for s in track.segments:
                out.append((Path(s.material_instance.path).name, s.target_timerange.start / 1e6,
                            s.source_timerange.start / 1e6, s.target_timerange.duration / 1e6, s.volume))
    return sorted(out, key=lambda s: s[1])


def peaks():
    return {t["file"]: t["peak"] for takes in sfx.kit()["sounds"].values() for t in takes}


@pytest.mark.parametrize("fps", [30, 25])
def test_peak_lands_one_frame_after_the_picture(media, fps):
    b = build(media, fps=fps, sfx=[{"sound": "hit", "at": "@c1"}, {"sound": "whoosh", "at": 3.0}])
    assert not b.errors, b.errors
    pk = peaks()
    (hit, hit_start, *_), (whoosh, w_start, *_) = sfx_segments(b)
    assert hit_start + pk[hit] == pytest.approx(2.0 + 1 / fps, abs=1e-5)
    assert w_start + pk[whoosh] == pytest.approx(3.0 + 1 / fps, abs=1e-5)


def test_transition_clip_and_text_cues(media):
    b = build(media,
              video=[{"id": "a", "src": str(media / "vertical.mp4"), "duration": 2,
                      "transition": {"name": "dissolve", "sfx": "whoosh"}},
                     {"id": "b", "src": str(media / "vertical.mp4"), "duration": 2, "sfx": "hit"}],
              texts=[{"text": "HI", "at": 0.5, "duration": 1, "sfx": {"sound": "pop"}, "echo": True}])
    assert not b.errors, b.errors
    pk = peaks()
    got = [(name[:-6], round(start + pk[name], 4)) for name, start, *_ in sfx_segments(b)]
    frame = round(1 / 30, 4)
    assert got == [("pop", round(0.5 + frame, 4)), ("whoosh", round(2 + frame, 4)), ("hit", round(2 + frame, 4))]


def test_repeats_rotate_through_takes(media):
    b = build(media, clips=5, sfx=[{"sound": "whoosh", "at": t} for t in (4, 1, 2, 3)]
              + [{"sound": "whoosh", "at": 5, "take": 3}])
    assert not b.errors, b.errors
    assert [s[0] for s in sfx_segments(b)] == ["whoosh_1.wav", "whoosh_2.wav", "whoosh_3.wav", "whoosh_1.wav",
                                               "whoosh_3.wav"]


def test_level_sits_a_few_db_over_the_music(media):
    music = {"src": str(media / "music.mp3"), "at": 0, "end": 3, "volume": 0.4}
    vo = {"src": str(media / "music.mp3"), "at": 0, "end": "end", "volume": 1.0, "track": "vo"}
    b = build(media, audio=[music, vo], sfx=[
        {"sound": "pop", "at": 1}, {"sound": "pop", "at": 2, "gain": -6},
        {"sound": "tick", "at": 3.5}, {"sound": "tick", "at": 4.5, "volume": 0.3}])
    assert not b.errors, b.errors
    vols = [s[4] for s in sfx_segments(b)]
    over = 10 ** (3 / 20)
    assert vols == pytest.approx([0.4 * over, 0.4 * over / 10 ** (6 / 20), over, 0.3], abs=0.002)


def test_lead_in_before_zero_and_tail_after_the_end_are_trimmed(media):
    b = build(media, clips=2, sfx=[{"sound": "riser", "at": 0.5}, {"sound": "hit", "at": 3.8}])
    assert not b.errors, b.errors
    pk = peaks()
    (riser, r_start, r_in, _, _), (hit, h_start, _, h_dur, _) = sfx_segments(b)
    assert r_start == 0 and r_in == pytest.approx(pk[riser] - 0.5 - 1 / 30, abs=1e-5)
    assert h_start + h_dur == pytest.approx(4.0, abs=1e-5)
    assert not b.warnings


def test_own_file_with_its_peak(media):
    b = build(media, sfx=[{"src": "media/music.mp3", "peak": 0.5, "at": 2}])
    assert not b.errors, b.errors
    (_, start, *_), = sfx_segments(b)
    assert start == pytest.approx(2 + 1 / 30 - 0.5, abs=1e-5)


@pytest.mark.parametrize("item, message", [
    ({"sound": "boing", "at": 1}, "sfx[0]: unknown sound 'boing'"),
    ({"at": 1}, "sfx[0]: give \"sound\""),
    ({"sound": "pop", "src": "media/music.mp3", "at": 1}, "not both"),
    ({"sound": "pop"}, "sfx[0]: \"at\" is required"),
    ({"sound": "pop", "at": 1, "take": 3}, "sfx[0].take must be at most 2"),
    ({"sound": "pop", "at": 1, "peak": 0.1}, "\"peak\" is only for your own"),
    ({"sound": "pop", "at": 9}, "past the end of the video"),
    ({"sound": "pop", "at": "@nope"}, "sfx[0].at: reference '@nope' matches no clip id"),
    ({"sound": "pop", "at": 1, "speed": 2}, "sfx[0]: unknown key(s) ['speed']"),
])
def test_bad_sfx_items(media, item, message):
    b = build(media, sfx=[item])
    assert any(message in e for e in b.errors), b.errors


def test_bad_cue_on_a_text(media):
    b = build(media, texts=[{"text": "HI", "at": 0.5, "duration": 1, "sfx": {"sound": "pop", "at": 2}}])
    assert any(e.startswith("texts[0]") and "unknown key(s) ['at']" in e for e in b.errors), b.errors

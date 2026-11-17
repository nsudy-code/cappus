"""build_draft.py --check: the demos validate, and bad specs get a clear message, never a traceback."""
import json

import pytest

from conftest import EXAMPLES, run


@pytest.mark.parametrize("spec, extra", [("demo.json", []), ("demo-pro.json", ["--allow-pro"])])
def test_demo_specs_validate(media, spec, extra):
    res = run("build_draft.py", EXAMPLES / spec, "--check", *extra)
    assert res.returncode == 0, res.stderr
    report = json.loads(res.stdout)
    assert report["status"].startswith("valid")
    assert not report.get("warnings")


def write_spec(tmp_path, media, **sections):
    spec = {"name": "edge", "video": [{"src": str(media / "vertical.mp4"), "duration": 3, "id": "a"}]}
    spec.update(sections)
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def music(media, **item):
    return [{"src": str(media / "music.mp3"), **item}]


def clip(m, **item):
    return {"video": [{"src": str(m / "vertical.mp4"), **item}]}


BAD = {
    "clip in as a word": (lambda m: clip(m, **{"in": "abc", "duration": 3}), "video[0].in must be a number, got 'abc'"),
    "clip out as a word": (lambda m: clip(m, out="abc"), "video[0].out must be a number, got 'abc'"),
    "clip duration as a word": (lambda m: clip(m, duration="abc"), "video[0].duration must be a number, got 'abc'"),
    "negative clip in": (lambda m: clip(m, **{"in": -1, "duration": 3}), "video[0].in must be at least 0, got -1"),
    "audio in as a word": (lambda m: {"audio": music(m, **{"in": "abc"})}, "audio[0].in must be a number, got 'abc'"),
    "audio at as a word": (lambda m: {"audio": music(m, at="abc")}, "audio[0].at: cannot parse time 'abc'"),
    "infinite text start": (
        lambda m: {"texts": [{"text": "hi", "at": float("inf"), "duration": 1}]},
        "texts[0].at must be a finite number"),
    "text duration as a word": (
        lambda m: {"texts": [{"text": "hi", "at": 0, "duration": "abc"}]},
        "texts[0].duration must be a number, got 'abc'"),
    "reference offset with two dots": (
        lambda m: {"texts": [{"text": "hi", "at": "@a+1.2.3", "duration": 1}]},
        "texts[0].at: cannot parse time '@a+1.2.3'"),
    "caption cue start as a word": (
        lambda m: {"captions": {"cues": [{"start": "abc", "end": 1, "text": "hi"}]}},
        "captions[0].cues[0].start must be a number, got 'abc'"),
    "audio keyframes without pairs": (
        lambda m: {"audio": music(m, keyframes={"volume": [0.5, 1.0]})},
        "audio[0].keyframes.volume: each point is [seconds_from_item_start, value], got 0.5"),
    "duck range that is not a pair": (
        lambda m: {"audio": music(m, duck={"ranges": ["@a"]})},
        "audio[0].duck.ranges[0]: each range is [start, end]"),
    "negative audio volume": (
        lambda m: {"audio": music(m, volume=-1)}, "audio[0].volume must be at least 0, got -1"),
    "audio speed zero": (
        lambda m: {"audio": music(m, speed=0)}, "audio[0].speed must be at least 0.1"),
    "text opacity above 1": (
        lambda m: {"texts": [{"text": "hi", "at": 0, "duration": 1, "opacity": 5}]},
        "texts[0].opacity must be at most 1, got 5"),
    "negative text size": (
        lambda m: {"texts": [{"text": "hi", "at": 0, "duration": 1, "size": -3}]},
        "texts[0].size must be more than 0, got -3"),
    "text as a bare string": (
        lambda m: {"texts": ["hello"]}, "texts[0] must be an object, got str"),
    "keyframe values as a string": (
        lambda m: {"video": [{"src": str(m / "vertical.mp4"), "duration": 3, "keyframes": {"opacity": "abc"}}]},
        "video[0].keyframes.opacity must be a list of [time, value] points"),
    "clip opacity above 1": (
        lambda m: {"video": [{"src": str(m / "vertical.mp4"), "duration": 3, "transform": {"opacity": 5}}]},
        "video[0].transform.opacity must be at most 1, got 5"),
    "negative clip volume": (
        lambda m: {"video": [{"src": str(m / "vertical.mp4"), "duration": 3, "volume": -1}]},
        "video[0].volume must be at least 0, got -1"),
    "filter intensity above 100": (
        lambda m: {"filters": [{"name": "vivid", "at": 0, "duration": 1, "intensity": 500}]},
        "filters[0].intensity must be at most 100, got 500"),
    "overlays as an object": (
        lambda m: {"overlays": {"src": "x"}}, "spec.overlays must be a list"),
    "fps that is not a number": (
        lambda m: {"fps": "fast"}, "spec.fps"),
}


@pytest.mark.parametrize("case", sorted(BAD))
def test_bad_spec_gets_a_clear_message(tmp_path, media, case):
    sections, expected = BAD[case]
    res = run("build_draft.py", write_spec(tmp_path, media, **sections(media)), "--check")
    assert res.returncode != 0
    assert "Traceback" not in res.stderr, res.stderr
    assert expected in res.stderr, res.stderr


def test_spec_that_is_not_an_object(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text("[1, 2]", encoding="utf-8")
    res = run("build_draft.py", path, "--check")
    assert res.returncode != 0 and "Traceback" not in res.stderr
    assert "the spec must be a JSON object" in res.stderr


def test_fps_2997_rounds_to_30_with_a_warning(tmp_path, media):
    res = run("build_draft.py", write_spec(tmp_path, media, fps=29.97), "--check")
    assert res.returncode == 0, res.stderr
    warnings = json.loads(res.stdout)["warnings"]
    assert any("29.97" in w and "using 30" in w for w in warnings), warnings


def test_single_effect_may_be_a_string(tmp_path, media):
    spec = {"video": [{"src": str(media / "vertical.mp4"), "duration": 3, "effects": "shake"}]}
    res = run("build_draft.py", write_spec(tmp_path, media, **spec), "--check")
    assert res.returncode == 0, res.stderr


def test_valid_audio_keyframes_and_duck(tmp_path, media):
    audio = music(media, duration=3, keyframes={"volume": [[0, 0.2], [2, 1.0]]},
                  duck={"ranges": [["@a", "@a.end"]], "to": 0.3})
    res = run("build_draft.py", write_spec(tmp_path, media, audio=audio), "--check")
    assert res.returncode == 0, res.stderr

"""Eased keyframes: the ease field, the CapCut curve encoding, and the linear fallback."""
import json

import pytest

import easing
import motion
from conftest import run


def build(tmp_path, spec):
    """Write a draft and return its draft_content.json."""
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({"name": "t-ease", **spec}), encoding="utf-8")
    drafts = tmp_path / "drafts"
    drafts.mkdir(exist_ok=True)
    res = run("build_draft.py", path, "--drafts-dir", drafts)
    assert res.returncode == 0, res.stderr
    return json.loads((drafts / "t-ease" / "draft_content.json").read_text(encoding="utf-8"))


def check(tmp_path, spec):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({"name": "t-ease", **spec}), encoding="utf-8")
    return run("build_draft.py", path, "--check")


def photo(media, **item):
    return [{"src": str(media / "photo.png"), "duration": 3, **item}]


def kf_lists(data, prop="KFTypeScaleX"):
    return [k["keyframe_list"] for t in data["tracks"] for s in t["segments"]
            for k in s.get("common_keyframes") or [] if k["property_type"] == prop]


# ---------- the curve math ----------

@pytest.mark.parametrize("name", easing.NAMES)
def test_every_ease_starts_at_0_and_ends_at_1(name):
    parsed = easing.parse(name, "t")
    if parsed:
        assert easing.bezier_at(parsed[0], 0) == 0 and easing.bezier_at(parsed[0], 1) == 1
        assert parsed[1] == name


def test_bezier_matches_known_css_values():
    # CSS ease-in-out (0.42, 0, 0.58, 1) is symmetric: half way in time is half way in value
    assert easing.bezier_at(easing.PRESETS["ease_in_out"][0], 0.5) == pytest.approx(0.5, abs=1e-6)
    assert easing.bezier_at(easing.PRESETS["ease_in"][0], 0.5) == pytest.approx(0.3154, abs=1e-3)
    assert easing.bezier_at(easing.PRESETS["back_out"][0], 0.6) > 1  # the rebound overshoots


@pytest.mark.parametrize("value, message", [
    ("bouncy", "unknown ease 'bouncy'"),
    ([1.5, 0, 0.5, 1], "x1 and x2 must be between 0 and 1"),
    ([0.2, 0, 0.5], "an ease is a name"),
    (7, "an ease is a name"),
])
def test_bad_ease(value, message):
    with pytest.raises(easing.EaseError, match=message):
        easing.parse(value, "t")


def test_sample_and_value_at_follow_the_curve():
    pts = [[0, 1.0], [2, 1.5, "ease_in"]]
    lin = easing.sample(pts, n=4)
    assert len(lin) == 5 and lin[0] == [0, 1.0] and lin[-1] == [2, 1.5]
    assert lin[2][1] == pytest.approx(1 + 0.5 * easing.bezier_at(easing.PRESETS["ease_in"][0], 0.5), abs=1e-4)
    assert easing.value_at(pts, 1) == pytest.approx(lin[2][1], abs=1e-4)
    assert easing.value_at([[0, 1.0], [2, 1.5]], 1) == 1.25


# ---------- what lands in the draft (format read from drafts CapCut 9.8 saved) ----------

def test_eased_segment_is_written_the_way_capcut_writes_it(tmp_path, media):
    data = build(tmp_path, {"video": photo(media, keyframes={"scale": [[0, 1.0], [1.5, 1.5, "ease_in"],
                                                                         [3, 1.0, "back_out"]]})})
    a, b, c = kf_lists(data)[0]
    assert a["curveType"] == b["curveType"] == c["curveType"] == "FreeCurveInOut"
    # Ease In over 1.5 s: CapCut wrote right_control x 630000 on the first keyframe, nothing on the second
    assert a["right_control"] == {"x": pytest.approx(630000), "y": 0.0}
    assert b["left_control"] == {"x": 0.0, "y": 0.0}
    dv = c["values"][0] - b["values"][0]
    assert b["right_control"]["x"] == pytest.approx(0.17 * 1.5e6)
    assert b["right_control"]["y"] == pytest.approx(0.89 * dv)
    assert c["left_control"]["x"] == pytest.approx((0.32 - 1) * 1.5e6)
    assert c["left_control"]["y"] == pytest.approx(0.27 * dv)
    graphs = {g["id"]: g for g in data["keyframe_graph_list"]}
    assert a["graphID"] == "" and len(graphs) == 2
    assert graphs[b["graphID"]] == {"id": b["graphID"], "resource_id": "7002056185805279746",
                                    "resource_name": "Ease In", "source_platform": 1, "graph_points": []}
    assert graphs[c["graphID"]]["resource_name"] == "Rebound Out"


def test_linear_keyframes_are_unchanged(tmp_path, media):
    data = build(tmp_path, {"video": photo(media, keyframes={"scale": [[0, 1.0], [3, 1.2]]})})
    for k in kf_lists(data)[0]:
        assert k["curveType"] == "Line" and k["graphID"] == ""
        assert k["left_control"] == k["right_control"] == {"x": 0.0, "y": 0.0}
    assert data["keyframe_graph_list"] == []


def test_default_ease_custom_curve_and_linear_override(tmp_path, media):
    kf = {"ease": "ease_in_out", "x": [[0, -0.2], [1, 0], [2, 0.1, "linear"], [3, 0.2, [0.9, 0, 0.1, 1]]]}
    data = build(tmp_path, {"video": photo(media, keyframes=kf)})
    k0, k1, k2, k3 = kf_lists(data, "KFTypePositionX")[0]
    assert k1["graphID"] and k2["graphID"] == "" and k3["graphID"] == ""  # custom curve: no preset
    assert k1["right_control"] == {"x": 0.0, "y": 0.0}  # the linear segment 1 -> 2 has no handles
    assert k2["right_control"]["x"] == pytest.approx(0.9 * 1e6)
    assert [g["resource_name"] for g in data["keyframe_graph_list"]] == ["Ease"]


def test_motion_presets_and_motion_moves_are_eased(tmp_path, media):
    spec = {"video": photo(media, motion="push_in", keyframes={"ease": "ease_in_out"}),
            "texts": [{"text": "HI", "at": 0, "duration": 2, "enter": "slam", "exit": "zoom_through"}]}
    data = build(tmp_path, spec)
    names = [g["resource_name"] for g in data["keyframe_graph_list"]]
    assert names.count("Ease") == 1 and "Cubic Out" in names and "Cubic In" in names
    for lst in kf_lists(data):
        assert any(k["curveType"] == "FreeCurveInOut" for k in lst)


def test_linear_keyframes_fallback_samples_every_curve(tmp_path, media):
    spec = {"linear_keyframes": True,
            "video": photo(media, keyframes={"scale": [[0, 1.0], [2, 1.5, "ease_in"]]}),
            "texts": [{"text": "HI", "at": 0, "duration": 2, "enter": "pop"}]}
    data = build(tmp_path, spec)
    assert data["keyframe_graph_list"] == []
    lists = kf_lists(data)
    assert all(k["curveType"] == "Line" for lst in lists for k in lst)
    assert len(lists[0]) == 7  # the eased segment, sampled 6 times


def test_enter_preset_values_end_at_rest_with_eases():
    pts = motion.enter_points("pop", 0.35, {"x": 0, "y": 0, "scale": 0.5, "opacity": 1}, "overlay")
    assert pts["scale"][-1][:2] == [0.35, 0.5] and pts["scale"][-1][2] == "cubic_in_out"
    assert len(pts["scale"]) == 3  # up to the peak, then settle: two segments


@pytest.mark.parametrize("spec, message", [
    ({"keyframes": {"scale": [[0, 1], [2, 1.2, "wobble"]]}}, "video[0].keyframes.scale ease at 2s: unknown ease 'wobble'"),
    ({"keyframes": {"ease": "wobble", "scale": [[0, 1], [2, 1.2]]}}, "video[0].keyframes.ease: unknown ease"),
    ({"keyframes": {"scale": [[0, 1], [2, 1, "ease_in", 4]]}}, "each point is [seconds_from_item_start, value] or [seconds, value, ease]"),
])
def test_bad_ease_in_a_spec_gets_a_clear_message(tmp_path, media, spec, message):
    res = check(tmp_path, {"video": photo(media, **spec)})
    assert res.returncode == 1 and message in res.stderr, res.stderr


def test_audio_volume_keyframes_take_no_ease(tmp_path, media):
    audio = [{"src": str(media / "music.mp3"), "duration": 3, "keyframes": {"volume": [[0, 0.2], [2, 1.0, "ease_in"]]}}]
    res = check(tmp_path, {"video": photo(media), "audio": audio})
    assert res.returncode == 1 and "each point is [seconds_from_item_start, value]" in res.stderr, res.stderr

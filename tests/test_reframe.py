"""Subject reframing: scan_footage.py follows a moving subject with a short path, and build_draft.py
turns transform.x_path into position keyframes on the clip."""
import json
import subprocess

import pytest

import scan_footage as sf
from conftest import run

BG = "geq=lum='100+40*sin(X/9)*cos(Y/13)+20*sin((X+2*Y)/23)':cb=140:cr=120,scale=1280:720,noise=alls=6:allf=t"


def box_clip(path, x_expr, seconds=4):
    """A 1280x720 clip: a white box (90x180) over a still textured background, at x = x_expr(t) px."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s=640x360:r=25:d={seconds}",
                    "-f", "lavfi", "-i", f"color=c=white:s=90x180:r=25:d={seconds}", "-filter_complex",
                    f"[0]{BG}[bg];[bg][1]overlay=x='{x_expr}':y=300", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@pytest.fixture(scope="module")
def boxes(tmp_path_factory):
    d = tmp_path_factory.mktemp("boxes")
    return {"moving": box_clip(d / "moving.mp4", "200+180*t"),          # crosses from the left third to the right
            "still": box_clip(d / "still.mp4", "850+6*sin(3*t)")}     # stays right of centre, barely moving


def test_a_box_that_crosses_the_frame_gets_a_path(boxes):
    x, path = sf.reframe(boxes["moving"], 0.5, 3.5, 1280, 720, 1080, 1920)
    assert path, "a subject crossing the frame should get a reframe_path"
    assert 2 <= len(path) <= 6
    times = [t for t, _ in path]
    assert times == sorted(times) and 0.5 <= times[0] and times[-1] <= 3.5
    # moving right in the source = the picture slides left to keep it centred (x falls)
    assert path[0][1] > 0.6 and path[-1][1] < -0.6, path
    assert all(a[1] >= b[1] - 0.05 for a, b in zip(path, path[1:])), path


def test_a_box_that_stays_put_keeps_one_offset(boxes):
    x, path = sf.reframe(boxes["still"], 0.5, 3.5, 1280, 720, 1080, 1920)
    assert path is None
    assert -1.6 < x < -0.7  # the box sits right of centre (~0.7 of the width): the picture moves left


def test_no_reframe_when_the_source_already_fits_the_canvas(boxes):
    assert sf.reframe(boxes["moving"], 0.5, 3.5, 1280, 720, 1920, 1080) == (0.0, None)


def test_simplify_keeps_the_bends_and_drops_the_straight_runs():
    line = [[t / 10, 1 - t / 10] for t in range(11)]
    assert sf.simplify(line, 0.05) == [line[0], line[-1]]
    vee = [[t, abs(t - 5) / 5] for t in range(11)]
    assert [p[0] for p in sf.simplify(vee, 0.05)] == [0, 5, 10]


def test_scan_gives_a_path_only_to_the_moving_shot(tmp_path, boxes):
    import shutil
    folder = tmp_path / "clips"
    folder.mkdir()
    for name, src in boxes.items():
        shutil.copy(src, folder / f"{name}.mp4")
    res = run("scan_footage.py", folder, "--out", tmp_path / "scan")
    assert res.returncode == 0, res.stderr
    rep = json.loads((tmp_path / "scan" / "footage.json").read_text(encoding="utf-8"))
    shots = {s["name"]: s for s in rep["ranked"] + rep["duplicates"]}
    assert shots["moving.mp4"].get("reframe_path"), shots["moving.mp4"]
    assert "reframe_path" not in shots["still.mp4"]
    for t, _ in shots["moving.mp4"]["reframe_path"]:
        assert shots["moving.mp4"]["best"]["in"] <= t <= shots["moving.mp4"]["best"]["out"]


def build(tmp_path, clip):
    spec = {"name": "t-path", "width": 1080, "height": 1920, "video": [clip]}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    drafts = tmp_path / "drafts"
    drafts.mkdir(exist_ok=True)
    res = run("build_draft.py", path, "--drafts-dir", drafts)
    assert res.returncode == 0, res.stderr
    data = json.loads((drafts / "t-path" / "draft_content.json").read_text(encoding="utf-8"))
    seg = next(t for t in data["tracks"] if t["type"] == "video")["segments"][0]
    return seg, {k["property_type"]: [(x["time_offset"], x["values"][0]) for x in k["keyframe_list"]]
                 for k in seg["common_keyframes"]}


def test_x_path_becomes_position_keyframes_in_source_time(tmp_path, media):
    # source seconds 1..3 played at 2x = a 1 s clip; the path's 2 s point lands half way.
    # CapCut reads a media clip's keyframe time as time in the file, so the points sit at 1, 2, 3 s.
    seg, kf = build(tmp_path, {"src": str(media / "landscape.mp4"), "in": 1, "out": 3, "speed": 2, "fit": "cover",
                               "transform": {"x_path": [[0.5, 0.8], [2, 0.0], [3.5, -0.8]]}})
    pts = kf["KFTypePositionX"]
    assert [t for t, _ in pts] == [1000000, 2000000, 3000000]
    assert [v for _, v in pts] == [pytest.approx(0.8 - 0.8 * 0.5 / 1.5), pytest.approx(0.0),
                                   pytest.approx(-0.8 * 1 / 1.5)]
    assert seg["clip"]["transform"]["x"] == pytest.approx(pts[0][1])


def test_x_path_works_with_a_push_in(tmp_path, media):
    _, kf = build(tmp_path, {"src": str(media / "landscape.mp4"), "in": 0, "out": 2, "fit": "cover",
                             "transform": {"x_path": [[0, 1.0], [2, -1.0]]}, "motion": "push_in"})
    assert [v for _, v in kf["KFTypePositionX"]] == [pytest.approx(1.0), pytest.approx(-1.0)]
    assert "KFTypeScaleX" in kf


def check(tmp_path, clip):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({"name": "t-bad", "video": [clip]}), encoding="utf-8")
    return run("build_draft.py", path, "--check")


@pytest.mark.parametrize("extra, message", [
    ({"transform": {"x": 0.2, "x_path": [[0, 0], [1, 1]]}}, "give x or x_path, not both"),
    ({"transform": {"x_path": [[0, 0], [1, 1]]}, "keyframes": {"x": [[0, 0], [1, 1]]}},
     "transform.x_path and keyframes both animate 'x'"),
    ({"transform": {"x_path": [[0, 0], [1, 1]]}, "motion": "pan_left"},
     "motion preset and transform.x_path both animate 'x'"),
    ({"transform": {"x_path": [[1, 0], [0.5, 1]]}}, "x_path: times must rise"),
    ({"transform": {"x_path": [[0, 0]]}}, "x_path: need at least 2"),
    ({"transform": {"x_path": [[0, "left"], [1, 1]]}}, "x_path value must be a number"),
])
def test_bad_x_path_gets_a_clear_message(tmp_path, media, extra, message):
    res = check(tmp_path, {"src": str(media / "landscape.mp4"), "in": 0, "out": 2, "fit": "cover", **extra})
    assert res.returncode == 1 and message in res.stderr, res.stderr

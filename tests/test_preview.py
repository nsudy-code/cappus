"""preview.py: the rough ffmpeg render Claude looks at when it cannot watch the draft in CapCut."""
import json
import subprocess

import numpy as np
import pytest
from PIL import Image

from conftest import EXAMPLES, run

import preview


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,width,height,r_frame_rate:format=duration:format_tags=title",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def frame_at(path, t, size):
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(path), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
    return np.frombuffer(out.stdout, np.uint8).reshape(size[1], size[0], 3).astype(int)


def write_spec(tmp_path, spec):
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec), encoding="utf-8")
    return p


@pytest.fixture
def red_square(tmp_path):
    p = tmp_path / "red.png"
    Image.new("RGB", (400, 400), (255, 0, 0)).save(p)
    return p


def test_demo_writes_a_labelled_preview_and_a_contact_sheet(tmp_path, media):
    out = tmp_path / "pv"
    res = run("preview.py", EXAMPLES / "demo.json", "--out", out)
    assert res.returncode == 0, res.stderr
    report = json.loads(res.stdout)
    assert "approximation" in report["status"]
    assert "transitions" in report["not_drawn"] and "effect tracks" in report["not_drawn"]
    info = probe(out / "preview.mp4")
    kinds = {s["codec_type"]: s for s in info["streams"]}
    assert (kinds["video"]["width"], kinds["video"]["height"]) == (540, 960)
    assert kinds["video"]["r_frame_rate"] == "15/1"
    assert "audio" in kinds                                         # clip sound and the music
    assert abs(float(info["format"]["duration"]) - report["duration"]) < 0.2
    assert "approximate" in info["format"]["tags"]["title"]
    sheet = Image.open(out / "sheet.jpg")
    assert sheet.format == "JPEG" and sheet.width > 500
    assert 4 <= len(report["sheet_times"]) <= 20


def test_contain_scale_and_x_position_land_where_capcut_puts_them(tmp_path, red_square):
    spec = write_spec(tmp_path, {"video": [{"src": str(red_square), "duration": 1,
                                            "transform": {"scale": 0.5, "x": 0.5}}]})
    out = tmp_path / "pv"
    preview.render(spec, out)
    f = frame_at(out / "preview.mp4", 0.5, (540, 960))
    # contained the square is 540 px wide in the preview; at scale 0.5 it is 270, centred at x = 405, y = 480
    assert f[480, 405, 0] > 200 and f[480, 405, 1] < 60
    assert f[480, 280, 0] > 200 and f[480, 530, 0] > 200             # spans 270..540
    assert f[480, 255].max() < 40 and f[330, 405].max() < 40         # black left of it and above it


def test_cover_fills_the_canvas_and_contain_letterboxes(tmp_path, media):
    spec = write_spec(tmp_path, {"video": [{"src": str(media / "landscape.mp4"), "in": 0, "out": 1, "fit": "cover"},
                                           {"src": str(media / "landscape.mp4"), "in": 0, "out": 1}]})
    out = tmp_path / "pv"
    preview.render(spec, out)
    cover = frame_at(out / "preview.mp4", 0.5, (540, 960))
    contain = frame_at(out / "preview.mp4", 1.5, (540, 960))
    assert cover[30].mean() > 40                                     # picture up to the top edge
    assert contain[30].max() < 30 and contain[480].mean() > 40       # black bars, picture in the middle


def test_motion_and_speed_follow_the_built_timeline(tmp_path, media):
    spec = {"video": [{"id": "a", "src": str(media / "landscape.mp4"), "in": 0, "out": 4, "speed": 2,
                       "fit": "cover", "motion": "push_in"},
                      {"id": "b", "src": str(media / "landscape.mp4"), "in": 0, "out": 2,
                       "motion": {"type": "pan_left", "amount": 0.1}}]}
    from build_draft import Builder
    b = Builder(spec, tmp_path, allow_pro=True)
    b.build()
    assert not b.errors
    layers, _, _ = preview.collect(b, (540, 960), 15)
    a, pan = [l for l in layers if isinstance(l, preview.VideoLayer)]
    assert (a.start, a.end) == (0, 2.0)                              # 4 s of source at 2x
    s0, s1 = preview._transform(a.seg, 0)["sx"], preview._transform(a.seg, 2.0)["sx"]
    assert s1 == pytest.approx(s0 * 1.12, rel=1e-3)                  # push_in grows 12 %
    x0, x1 = preview._transform(pan.seg, 0)["x"], preview._transform(pan.seg, 2.0)["x"]
    assert (x0, x1) == (pytest.approx(0.1), pytest.approx(-0.1))
    for layer in layers:
        layer.close()


def test_text_shows_only_in_its_time_and_at_its_y(tmp_path, red_square):
    spec = write_spec(tmp_path, {
        "video": [{"src": str(red_square), "duration": 2, "transform": {"scale": 0.01}}],
        "texts": [{"text": "HELLO", "at": 1, "end": 2, "y": 0.5, "size": 12, "color": "#FFFFFF"}]})
    out = tmp_path / "pv"
    preview.render(spec, out)
    before = frame_at(out / "preview.mp4", 0.5, (540, 960))
    during = frame_at(out / "preview.mp4", 1.5, (540, 960))
    rows = np.where((during[:800] > 200).all(axis=2).any(axis=1))[0]  # skip the label at the bottom
    assert rows.size and 200 < rows.mean() < 280                     # y = 0.5 is a quarter down: 240
    assert not (before[:800] > 200).all(axis=2).any()


def test_a_broken_spec_is_reported_not_rendered(tmp_path):
    spec = write_spec(tmp_path, {"video": [{"src": "missing.mp4"}]})
    res = run("preview.py", spec, "--out", tmp_path / "pv")
    assert res.returncode == 1
    assert "missing.mp4" in res.stderr
    assert not (tmp_path / "pv" / "preview.mp4").exists()


def test_eased_keyframes_follow_their_curve_not_a_straight_line():
    import easing
    from pycapcut.keyframe import Keyframe

    easing.install()
    a, b = Keyframe(0, 0.0), Keyframe(1_000_000, 1.0)
    a.values, b.values = [0.0], [1.0]

    class KL:
        keyframes = [a, b]

        class keyframe_property:
            name = "position_y"

    easing.apply(KL, {1_000_000: easing.parse("cubic_out", "test")}, easing.Graphs())

    class Seg:
        common_keyframes = [KL]

    pts = preview._kf(Seg)["position_y"]
    mid = preview._at(pts, 0.5, None)
    assert mid == pytest.approx(easing.bezier_at(easing.PRESETS["cubic_out"][0], 0.5), abs=1e-6)
    assert mid > 0.7  # cubic out is well past halfway at half time; a straight line would give 0.5
    assert preview._at([(0, 0.0, None), (1, 1.0, None)], 0.5, None) == pytest.approx(0.5)


def test_a_spec_with_sound_effects_renders_without_stalling(tmp_path, media):
    # many short audio inputs once made ffmpeg fill its stderr pipe and stall the render
    import os
    import sys
    from conftest import SCRIPTS

    out = tmp_path / "pv"
    res = subprocess.run([sys.executable, str(SCRIPTS / "preview.py"), str(EXAMPLES / "demo-sfx.json"), "--out", str(out)],
                         capture_output=True, text=True, encoding="utf-8", timeout=180,
                         env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    assert res.returncode == 0, res.stderr
    kinds = {s["codec_type"] for s in probe(out / "preview.mp4")["streams"]}
    assert kinds == {"video", "audio"}

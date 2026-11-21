"""faces.py: crops, punch-ins and text placed around the speaker's face; cut_talk.py using it."""
import json
import sys

import pytest

import faces
from test_cut_talk import TAKE, LENGTH, words  # noqa: F401  (the same synthetic take)


def test_vertical_source_centred_face_needs_no_wide_move():
    wide, punched = faces.framing((0.5, 0.3, 0.2, 0.12), 1080, 1920, 1080, 1920, 1.2)
    assert wide == {}
    # face 0.4 of the half-canvas above centre stays put: y = 0.4 * (1 - 1.2)
    assert punched == {"scale": 1.2, "y": -0.08}


def test_wide_source_crop_centres_the_face_and_never_shows_the_edge():
    # 16:9 on 9:16 under cover: the picture is 3.16 canvas widths wide, x can move +-2.16
    wide, punched = faces.framing((0.315, 0.2, 0.06, 0.11), 1920, 1080, 1080, 1920, 1.18)
    assert wide["x"] == pytest.approx(1.169, abs=0.01)
    assert punched["x"] > wide["x"] and punched["scale"] == 1.18
    edge, _ = faces.framing((0.0, 0.5, 0.06, 0.11), 1920, 1080, 1080, 1920, 1.18)
    assert edge["x"] == pytest.approx(2.16, abs=0.01)  # face at the very edge: clamped, no black bar


def test_text_spots_stay_off_the_face():
    cap, title = faces.text_spots((0.5, 0.3, 0.2, 0.12), 1080, 1920, 1080, 1920)
    assert cap == faces.CAPTION_Y and title is not None
    # a face low in the frame: captions go above it, not over the mouth
    cap, _ = faces.text_spots((0.5, 0.82, 0.3, 0.17), 1080, 1920, 1080, 1920)
    face_top = (0.5 - 0.82) * 2 + 0.17 * 1.18
    assert cap > face_top
    # the head at the very top: the title sits under the chin, above the captions
    cap, title = faces.text_spots((0.5, 0.12, 0.2, 0.12), 1080, 1920, 1080, 1920)
    assert cap == faces.CAPTION_Y and cap + 0.3 < title < 0.5


def test_path_of_keeps_the_bends():
    pts = [(t / 2, 0, 0, 0, 0) for t in range(21)]
    xs = [1.0 if t < 10 else 1.0 - (t - 10) * 0.2 for t in range(21)]
    path = faces.path_of(pts, xs)
    assert path[0] == [0.0, 1.0] and path[-1][0] == 10.0 and len(path) <= 5


@pytest.fixture
def wide_talk(tmp_path):
    """A 16:9 version of the take (tones for words), for crops to vertical."""
    import subprocess
    gate = "+".join(f"between(t,{s},{e})" for _, s, e in TAKE)
    video = tmp_path / "talk.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x335577:s=640x360:r=30:d={LENGTH}",
                    "-f", "lavfi", "-i", f"aevalsrc='0.5*sin(2*PI*220*t)*({gate})':d={LENGTH}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)], check=True)
    (tmp_path / "talk.transcript.json").write_text(json.dumps(
        {"language": "id", "duration": LENGTH, "words": words(TAKE), "segments": []}), encoding="utf-8")
    return video


def run_in_process(monkeypatch, capsys, video, track, *args):
    import cut_talk
    monkeypatch.setattr(faces, "available", lambda: True)
    monkeypatch.setattr(faces, "track", lambda *a, **k: track)
    monkeypatch.setattr(sys, "argv", ["cut_talk.py", str(video), *args])
    assert cut_talk.main() == 0
    report = json.loads(capsys.readouterr().out)
    return report, json.loads(video.with_suffix(".cut.json").read_text(encoding="utf-8"))


def test_cut_talk_crops_to_the_face_and_follows_it(wide_talk, monkeypatch, capsys):
    # the speaker stands left, then walks right during the last sentence (from 10.8 s)
    track = [(t / 2, 0.3 if t / 2 < 10.8 else min(0.75, 0.3 + (t / 2 - 10.8) * 0.3), 0.3, 0.06, 0.11)
             for t in range(int(LENGTH * 2))]
    report, spec = run_in_process(monkeypatch, capsys, wide_talk, track)
    assert report["faces"]["found"] == 1.0 and report["faces"]["clips_following_face"] >= 1
    first, last = spec["video"][0], spec["video"][-1]
    assert first["transform"]["x"] > 1.0  # face left of centre: the crop moves the picture right
    xs = [x for _, x in last["transform"]["x_path"]]
    assert xs[0] > 0 > xs[-1]  # follows the walk across


def test_cut_talk_moves_captions_up_when_the_face_is_low(tmp_path, monkeypatch, capsys):
    import subprocess
    video = tmp_path / "talk.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f=220:d={LENGTH}",
                    "-f", "lavfi", "-i", f"color=c=0x335577:s=360x640:r=30:d={LENGTH}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)], check=True)
    (tmp_path / "talk.transcript.json").write_text(json.dumps(
        {"language": "id", "duration": LENGTH, "words": words(TAKE), "segments": []}), encoding="utf-8")
    track = [(t / 2, 0.5, 0.8, 0.3, 0.17) for t in range(int(LENGTH * 2))]
    report, spec = run_in_process(monkeypatch, capsys, video, track, "--no-silence")
    face_top = (0.5 - 0.8) * 2 + 0.17 * 1.18  # spec y of the top of the (punched) face
    assert spec["styles"]["caption"]["y"] > face_top and spec["captions"]["style"] == "caption"


def test_face_y_skips_detection(wide_talk):
    from conftest import run
    res = run("cut_talk.py", wide_talk, "--face-y", "0.3")
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["faces"] == {"found": 0.0, "framed_for_face_y": 0.3}

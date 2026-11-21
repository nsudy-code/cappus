"""cut_talk.py: a talking-head take becomes jump cuts without its pauses, fillers and flubbed starts."""
import json
import subprocess

import pytest

import cut_talk
from conftest import run

# A short Indonesian take: greeting, a false start and an "eh", a point, a hook line, and a sentence
# whose two halves start alike on purpose (parallel, not a retake).
TAKE = [
    ("Halo", 0.5, 0.9), ("semuanya.", 0.9, 1.5),
    ("Jadi", 2.6, 2.9), ("yang,", 2.9, 3.2),
    ("eh,", 3.5, 3.8),
    ("jadi", 4.2, 4.5), ("yang", 4.5, 4.7), ("pertama", 4.7, 5.2), ("minum", 5.2, 5.5), ("air", 5.5, 5.8),
    ("putih.", 5.8, 6.3),
    ("Ternyata", 7.5, 8.0), ("90%", 8.0, 8.5), ("orang", 8.5, 8.8), ("kurang", 8.8, 9.2), ("minum.", 9.2, 9.7),
    ("Kalau", 10.8, 11.1), ("kamu", 11.1, 11.3), ("lapar,", 11.3, 11.7), ("kalau", 11.8, 12.1),
    ("kamu", 12.1, 12.3), ("haus.", 12.3, 12.8),
]
LENGTH = 13.5


def words(take):
    return [{"word": w, "start": s, "end": e, "p": 0.95} for w, s, e in take]


@pytest.fixture
def talk(tmp_path):
    """talk.mp4 with a tone wherever a word is said and silence elsewhere, plus its transcript."""
    spans = []
    for w, s, e in TAKE:
        if spans and abs(spans[-1][1] - s) < 1e-6:
            spans[-1][1] = e
        else:
            spans.append([s, e])
    gate = "+".join(f"between(t,{s},{e})" for s, e in spans)
    video = tmp_path / "talk.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x335577:s=360x640:r=30:d={LENGTH}",
                    "-f", "lavfi", "-i", f"aevalsrc='0.5*sin(2*PI*220*t)*({gate})':d={LENGTH}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)], check=True)
    transcript = {"source": str(video), "language": "id", "duration": LENGTH, "words": words(TAKE),
                  "segments": []}
    (tmp_path / "talk.transcript.json").write_text(json.dumps(transcript), encoding="utf-8")
    return video


def cut(video, *args):
    res = run("cut_talk.py", video, *args)
    assert res.returncode == 0, res.stderr
    spec = json.loads((video.parent / "talk.cut.json").read_text(encoding="utf-8"))
    return json.loads(res.stdout), spec


def test_cuts_pauses_fillers_and_the_false_start(talk):
    report, spec = cut(talk)
    clips = spec["video"]
    assert [c["src"] for c in clips] == ["talk.mp4"] * 4
    kept = " ".join(c["note"] for c in clips)
    assert kept == ("Halo semuanya. jadi yang pertama minum air putih. Ternyata 90% orang kurang minum. "
                    "Kalau kamu lapar, kalau kamu haus.")
    # every clip starts a little before its first word and ends a little after its last
    assert clips[1]["in"] == pytest.approx(4.2 - 0.12, abs=0.06)
    assert clips[1]["out"] == pytest.approx(6.3 + 0.12, abs=0.06)
    retake = next(r for r in report["removed"] if r["why"] == "retake")
    assert retake["text"] == "Jadi yang, eh,"
    assert retake["kept_take"].startswith("jadi yang pertama")
    assert report["edit_seconds"] < LENGTH - 4


def test_punch_ins_alternate_and_keep_the_face_up(talk):
    _, spec = cut(talk, "--punch", "1.2", "--face-y", "0.3")
    scales = [c.get("transform", {}).get("scale", 1) for c in spec["video"]]
    assert scales == [1, 1.2, 1, 1.2]
    # face 40% of the half-canvas above centre stays put: y = 0.4 * (1 - 1.2)
    assert spec["video"][1]["transform"]["y"] == pytest.approx(-0.08)
    _, spec = cut(talk, "--punch", "1")
    assert all("transform" not in c for c in spec["video"])


def test_eased_zoom_lands_on_the_key_word_and_other_clips_drift(talk):
    report, spec = cut(talk, "--punch", "1.2", "--face-y", "0.3")
    clips = spec["video"]
    # hard punch-ins still alternate at the cuts
    assert [c.get("transform", {}).get("scale", 1) for c in clips] == [1, 1.2, 1, 1.2]
    zoom = clips[2]["keyframes"]  # "Ternyata 90% orang kurang minum." on a wide clip
    assert [z["word"] for z in report["camera"]["zooms"]] == ["90%"]
    lands = 8.0 - clips[2]["in"] + cut_talk.ZOOM_LEAD
    assert zoom["scale"][2] == [pytest.approx(lands, abs=0.002), pytest.approx(1.15), "cubic_out"]
    assert zoom["scale"][1][:2] == [pytest.approx(lands - cut_talk.ZOOM_IN, abs=0.002), 1.0]
    # the face 40% above centre stays put while it zooms: y = 0.4 * (1 - 1.15)
    assert zoom["y"][2][1] == pytest.approx(-0.06, abs=1e-3)
    # every other clip drifts slowly, in and out by turns, around its own framing
    for c in (clips[0], clips[1], clips[3]):
        s = [p[1] for p in c["keyframes"]["scale"]]
        base = c.get("transform", {}).get("scale", 1)
        assert sorted(s) == [pytest.approx(base), pytest.approx(base * 1.03)]
    assert report["camera"]["drifting_clips"] == 3
    check = run("build_draft.py", talk.parent / "talk.cut.json", "--check")
    assert check.returncode == 0, check.stdout + check.stderr


@pytest.mark.parametrize("style, scales, moving", [
    ("smooth", [1, 1, 1, 1], True),      # no hard punch-ins, the eased zooms and drift stay
    ("cut", [1, 1.2, 1, 1.2], False),    # punch-ins only, as before
    ("off", [1, 1, 1, 1], False),
])
def test_zoom_styles(talk, style, scales, moving):
    report, spec = cut(talk, "--punch", "1.2", "--face-y", "0.3", "--zoom", style)
    assert [c.get("transform", {}).get("scale", 1) for c in spec["video"]] == scales
    assert any("keyframes" in c for c in spec["video"]) == moving
    assert bool(report["camera"]["zooms"]) == moving


def test_hooks_rank_the_surprising_line_and_tease_it(talk):
    report, spec = cut(talk, "--hook-first", "--hooks", "10")
    assert report["hooks"][0]["text"] == "Ternyata 90% orang kurang minum."
    greeting = next(h for h in report["hooks"] if h["text"].startswith("Halo"))
    assert "a greeting" in greeting["why"]
    hook = spec["video"][0]
    assert hook["id"] == "hook" and hook["in"] == pytest.approx(7.38, abs=0.06)
    assert [c["id"] for c in spec["video"][1:]] == ["t1", "t2", "t3", "t4"]


def test_the_spec_builds_and_captions_keep_every_kept_word(talk):
    _, spec = cut(talk, "--look", "clean_tech")
    caption_file = talk.parent / spec["captions"]["transcript"]
    cut_words = [w["word"] for w in json.loads(caption_file.read_text(encoding="utf-8"))["words"]]
    assert "eh," not in cut_words and cut_words[:3] == ["Halo", "semuanya.", "jadi"]
    res = run("build_draft.py", talk.parent / "talk.cut.json", "--check")
    assert res.returncode == 0, res.stderr
    check = json.loads(res.stdout)
    line = next(t for t in check["timeline"] if "captions" in t)
    assert "synced to 4 clip(s) of talk.mp4" in line and "were cut" not in line
    assert not check["warnings"]


def test_broll_fills_slots_muted_and_full_frame(talk, media):
    report, spec = cut(talk, "--broll-every", "3", "--broll", media / "landscape.mp4")
    assert report["broll_slots"]
    (o,) = spec["overlays"]
    assert o["mute"] is True and o["fit"] == "cover" and o["track"] == "broll"
    assert o["at"] >= 3.0 and 1.2 <= o["duration"] <= 2.0
    assert run("build_draft.py", talk.parent / "talk.cut.json", "--check").returncode == 0


def test_word_times_only_without_the_silence_check(talk):
    report, spec = cut(talk, "--no-silence", "--keep-fillers", "--keep-retakes")
    notes = " ".join(c["note"] for c in spec["video"])
    assert notes.startswith("Halo semuanya. Jadi yang, eh, jadi yang pertama")
    assert "retake" not in report["cut_seconds"]


def test_missing_transcript_says_what_to_run(tmp_path, media):
    res = run("cut_talk.py", media / "vertical.mp4", "--out", tmp_path / "x.json")
    assert res.returncode != 0
    assert "run transcribe.py vertical.mp4 first" in res.stderr
    assert "Traceback" not in res.stderr


@pytest.mark.parametrize("word, filler", [
    ("um,", True), ("Uhm", True), ("eh", True), ("Ehm...", True), ("emm", True), ("hmm", True),
    ("anu", True), ("ER", False), ("EM", False), ("ember", False), ("air", False), ("a", False),
])
def test_filler_words(word, filler):
    assert cut_talk.is_filler(word) is filler


def mark(take):
    ws = words(take)
    drop = {}
    cut_talk.mark_retakes(ws, drop)
    return [ws[i]["word"] for i in sorted(drop)]


def test_retakes_keep_the_last_take_and_leave_parallel_lines():
    assert mark([("Most", 0, 0.3), ("people", 0.3, 0.6), ("think,", 0.6, 0.9),
                 ("most", 1.5, 1.8), ("people", 1.8, 2.1), ("think", 2.1, 2.4), ("naps", 2.4, 2.8),
                 ("help.", 2.8, 3.2)]) == ["Most", "people", "think,"]
    assert mark([("Kalau", 0, 0.3), ("kamu", 0.3, 0.5), ("lapar,", 0.5, 0.9),
                 ("kalau", 1.0, 1.3), ("kamu", 1.3, 1.5), ("haus.", 1.5, 1.9)]) == []
    assert mark([("Yang", 0, 0.3), ("pertama,", 0.3, 0.8), ("minum.", 0.8, 1.2),
                 ("Yang", 2.0, 2.3), ("kedua,", 2.3, 2.8), ("tidur.", 2.8, 3.2)]) == []
    # a stutter inside one phrase
    assert mark([("saya", 0, 0.2), ("mau", 0.2, 0.4), ("saya", 0.4, 0.6), ("mau", 0.6, 0.8),
                 ("pulang.", 0.8, 1.2)]) == ["saya", "mau"]
    # far apart is a callback, not a retake
    assert mark([("Ini", 0, 0.3), ("penting", 0.3, 0.7), ("banget.", 0.7, 1.1),
                 ("Ini", 20, 20.3), ("penting", 20.3, 20.7), ("banget", 20.7, 21.1), ("loh.", 21.1, 21.4)]) == []


def test_snapped_words_move_into_the_clip_that_plays_them():
    ws = words([("That", 15.28, 15.80), ("means", 15.80, 16.10)])
    # Whisper put "That" mostly in the pause before 15.56, where the clip starts
    out = cut_talk.snap_words(ws, {}, [[15.56, 17.7]], [])
    assert out[0]["start"] >= 15.56 and (out[0]["start"] + out[0]["end"]) / 2 >= 15.56
    # a word that overlaps a dropped hesitation more than a clip is left out
    ws = words([("a", 9.78, 10.42), ("coffee", 10.42, 11.12)])
    out = cut_talk.snap_words(ws, {}, [[7.4, 9.9], [10.79, 13.2]], [[10.17, 10.58]])
    assert [w["word"] for w in out] == ["coffee"]

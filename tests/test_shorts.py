"""shorts.py: the best self-contained stretches of a long recording, each cut into its own spec."""
import json
import subprocess

import pytest

import cut_talk
import shorts
from conftest import run

BODY = "Minum air putih delapan gelas setiap hari supaya badan tetap segar."
PARTS = [
    # opens mid-thought: a weak start for a short
    ["Jadi itu tadi yang saya bilang soal tidur.", *[BODY] * 6],
    # a claim with a number, to the viewer: the best opening
    ["Ternyata 90% orang kurang minum, dan kamu mungkin salah satunya!", *[BODY] * 6],
    # a greeting
    ["Halo semuanya selamat datang kembali.", *[BODY] * 6],
]
WORD, SENTENCE_GAP, PART_GAP = 0.36, 0.3, 3.5


def transcript():
    words, t = [], 1.0
    for part in PARTS:
        for sentence in part:
            for w in sentence.split():
                words.append({"word": w, "start": round(t, 2), "end": round(t + WORD - 0.04, 2), "p": 0.95})
                t += WORD
            t += SENTENCE_GAP
        t += PART_GAP
    return words, t + 1


@pytest.fixture
def long_talk(tmp_path):
    words, length = transcript()
    video = tmp_path / "kajian.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x335577:s=360x640:r=30:d={length}",
                    "-f", "lavfi", "-i", f"sine=frequency=220:duration={length}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)], check=True)
    (tmp_path / "kajian.transcript.json").write_text(json.dumps({"words": words, "segments": []}), encoding="utf-8")
    return video


def test_ranks_the_hook_first_and_never_starts_mid_thought():
    words, _ = transcript()
    sentences = cut_talk.sentences_of(words, {})
    cands = shorts.candidates(words, sentences, 20, 60, 30)
    assert cands and all(20 <= c["seconds"] <= 60 for c in cands)
    best = max(cands, key=lambda c: c["score"])
    assert best["opening"].startswith("Ternyata 90%")
    jadi = [c for c in cands if c["opening"].startswith("Jadi")]
    assert jadi and all("starts mid-thought" in " ".join(c["why"]) for c in jadi)
    # no short runs across the long pause between two parts
    for c in cands:
        assert sum(1 for p in ("Jadi itu", "Ternyata", "Halo") if p in c["opening"]) <= 1
        assert c["seconds"] < 30  # each part is ~25 s; crossing a break would make it longer


def test_pick_keeps_the_best_that_do_not_overlap():
    cands = [{"from": 0, "to": 30, "score": 5}, {"from": 10, "to": 40, "score": 4}, {"from": 50, "to": 80, "score": 3}]
    assert [c["from"] for c in shorts.pick(cands, 3)] == [0, 50]


def test_writes_one_spec_per_short(long_talk):
    res = run("shorts.py", long_talk, "--count", "2", "--look", "talk")
    assert res.returncode == 0, res.stderr
    rep = json.loads(res.stdout)
    assert len(rep["shorts"]) == 2
    first = min(rep["shorts"], key=lambda s: s["rank"])
    assert first["opening"].startswith("Ternyata")
    for s in rep["shorts"]:
        spec = json.loads(open(s["spec"], encoding="utf-8").read())
        assert spec["look"] == "talk" and spec["name"].startswith("kajian-short")
        ins = [v["in"] for v in spec["video"]]
        assert s["from"] - 0.5 <= min(ins) and max(v["out"] for v in spec["video"]) <= s["to"] + 0.5
        check = run("build_draft.py", s["spec"], "--check")
        assert check.returncode == 0, check.stdout + check.stderr
    listed = json.loads(run("shorts.py", long_talk, "--list").stdout)
    assert all("spec" not in s for s in listed["shorts"])


def test_explains_when_nothing_fits(long_talk):
    res = run("shorts.py", long_talk, "--min", "50", "--max", "55")
    assert res.returncode != 0 and "--min" in res.stderr

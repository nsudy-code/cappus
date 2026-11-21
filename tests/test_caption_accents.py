"""Caption highlights (the word being said) and keywords, the edu/talk looks, and the lower third."""
import json

import pytest

import cut_talk
from build_draft import Builder
from conftest import run
from test_cut_talk import cut, talk  # noqa: F401  (the synthetic take fixture)

WORDS = [{"word": "Ternyata", "start": 0.5, "end": 1.0}, {"word": "90%", "start": 1.0, "end": 1.5},
         {"word": "orang", "start": 1.5, "end": 1.8}, {"word": "kurang", "start": 1.8, "end": 2.2},
         {"word": "minum.", "start": 2.2, "end": 2.7}]


def captions(media, cap, look=None):
    spec = {"video": [{"src": str(media / "vertical.mp4"), "duration": 4}],
            "captions": dict({"words": WORDS, "source": None, "max_words": 3}, **cap)}
    if look:
        spec["look"] = look
    b = Builder(spec, media.parent, allow_pro=True)
    b.build()
    assert not b.errors, b.errors
    segs = [s for t in b.script.tracks.values() if t.name == "captions" for s in t.segments]
    out = []
    for s in segs:
        c = json.loads(s.export_material()["content"])
        out.append((round(s.target_timerange.start / 1e6, 2), c["text"],
                    [(st["range"], [round(v, 2) for v in st["fill"]["content"]["solid"]["color"]], st["size"])
                     for st in c["styles"]]))
    return out


def test_plain_captions_keep_one_style(media):
    out = captions(media, {})
    assert [t for _, t, _ in out] == ["Ternyata 90% orang", "kurang minum."]
    assert all(len(st) == 1 for _, _, st in out)


def test_highlight_lights_up_each_word_as_it_is_said(media):
    out = captions(media, {"highlight": {"color": "#FF0000"}})
    assert [(t, txt) for t, txt, _ in out][:3] == [(0.5, "Ternyata 90% orang"), (1.0, "Ternyata 90% orang"),
                                                    (1.5, "Ternyata 90% orang")]
    red = [[r for r, color, _ in st if color == [1.0, 0.0, 0.0]] for _, _, st in out]
    assert red == [[[0, 8]], [[9, 12]], [[13, 18]], [[0, 6]], [[7, 13]]]


def test_keywords_are_colored_and_bigger_in_every_piece(media):
    out = captions(media, {"keywords": ["90%", "minum"], "highlight": {"color": "#FF0000", "upcoming": "#888888"}},
                   look="edu")
    first = out[0][2]
    # "Ternyata" said (red), "90%" a keyword not yet said (grey, keyword size), "orang" grey
    assert first[0] == ([0, 8], [1.0, 0.0, 0.0], 11.0)
    assert first[2] == ([9, 12], [0.53, 0.53, 0.53], pytest.approx(11 * 1.2))
    # with no highlight, keywords take the look's accent
    plain = captions(media, {"keywords": ["minum"]}, look="edu")
    assert ([7, 13], [0.13, 0.83, 0.93], pytest.approx(11 * 1.2)) in plain[1][2]


def test_uppercase_and_no_punctuation_keep_the_word_ranges(media):
    out = captions(media, {"uppercase": True, "punctuation": False, "highlight": True}, look="talk")
    assert out[-1][1] == "KURANG MINUM"
    assert out[-1][2][-1][0] == [7, 12]


def test_highlight_needs_word_times(tmp_path, media):
    spec = {"video": [{"src": str(media / "vertical.mp4"), "duration": 4}],
            "captions": {"cues": [{"start": 0, "end": 1, "text": "hi"}], "highlight": True}}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    res = run("build_draft.py", path, "--check")
    assert res.returncode != 0 and "need word times" in res.stdout + res.stderr


def test_keywords_pick_numbers_then_long_uncommon_words():
    words = [{"word": w, "start": i, "end": i + 0.5} for i, w in enumerate(
        "Ternyata 90% orang kurang minum. Dehidrasi bikin pusing dan lemas.".split())]
    sentences = [[0, 1, 2, 3, 4], [5, 6, 7, 8, 9]]
    assert cut_talk.keywords_of(words, sentences) == ["90%", "dehidrasi"]


def test_cut_talk_with_the_talk_look_and_a_lower_third(talk):  # noqa: F811
    report, spec = cut(talk, "--look", "talk", "--speaker", "dr. Aisya", "--role", "Dokter Umum")
    cap = spec["captions"]
    assert cap["uppercase"] and cap["highlight"] == {"color": "$accent"} and cap["max_words"] == 3
    assert "90%" in cap["keywords"]["words"] and report["keywords"]["used"]
    name, role = spec["texts"]
    assert (name["style"], role["style"], name["text"]) == ("name", "role", "dr. Aisya")
    # the longer name box is centred further right, so both boxes start at the same left edge
    assert name["x"] > role["x"] and name["y"] > role["y"]
    check = run("build_draft.py", talk.parent / "talk.cut.json", "--check")
    assert check.returncode == 0, check.stdout + check.stderr


def test_cut_talk_without_a_look_reports_keywords_unused(talk):  # noqa: F811
    report, spec = cut(talk)
    assert "keywords" not in spec["captions"] and not report["keywords"]["used"]

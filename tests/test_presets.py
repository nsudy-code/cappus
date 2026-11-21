"""Series presets: saving, checking, and filling a spec or a cut_talk.py run from one."""
import json

import pytest

import presets
from build_draft import Builder, SpecError
from conftest import run
from test_cut_talk import cut, talk  # noqa: F401  (the synthetic take fixture)


def spec_for(media, **extra):
    return dict({"video": [{"src": str(media / "vertical.mp4"), "duration": 4}]}, **extra)


@pytest.fixture
def aisya(media):
    presets.save("dr Aisya", {"look": "edu", "brand": {"accent": "#14B8A6"}, "speaker": "dr. Aisya",
                              "role": "Dokter Umum", "handle": {"text": "@dr.aisya"},
                              "logo": {"src": str((media / "photo.png").resolve())},
                              "captions": {"max_words": 2, "keywords": {"words": ["Aisya"], "scale": 1.4}},
                              "styles": {"caption": {"size": 13, "y": -0.5}},
                              "talk": {"punch": 1.2, "max_pause": 0.4}})
    return "dr-aisya"


def test_save_slugs_the_name_and_updates_key_by_key(aisya, cappus_home):
    path = cappus_home / "presets" / "dr-aisya.json"
    assert path.is_file() and presets.names() == ["dr-aisya"]
    presets.save("DR AISYA", {"brand": {"accent": "#0EA5E9"}, "talk": {"pad": 0.1}})
    p = presets.load("dr-aisya")
    assert p["name"] == "dr-aisya" and p["brand"] == {"accent": "#0EA5E9"}
    assert p["talk"] == {"punch": 1.2, "max_pause": 0.4, "pad": 0.1} and p["speaker"] == "dr. Aisya"


@pytest.mark.parametrize("data, says", [
    ({"colour": "red"}, "unknown key"),
    ({"look": "nope"}, "nope"),
    ({"brand": {"accent": "#FF0000"}}, "need a look"),
    ({"talk": {"speed": 2}}, "talk: unknown"),
    ({"handle": {"y": 0.8}}, "needs \"text\""),
    ({"logo": {"src": "logo.png"}}, "absolute"),
])
def test_bad_presets_are_refused(data, says):
    with pytest.raises(presets.PresetError, match=says.replace("\"", ".")):
        presets.validate(data)


def test_unknown_preset_names_the_saved_ones(aisya):
    with pytest.raises(presets.PresetError, match="Saved presets: dr-aisya"):
        presets.load("dr-hans")


def test_apply_fills_under_the_spec(aisya, media):
    spec = spec_for(media, preset=aisya, styles={"caption": {"y": -0.2}},
                    captions={"words": [], "max_words": 4, "keywords": ["90%"]})
    out = presets.apply(spec)
    assert "preset" not in out and "preset" in spec  # a copy
    assert out["look"] == "edu" and out["brand"] == {"accent": "#14B8A6"}
    assert out["styles"]["caption"] == {"size": 13, "y": -0.2}  # the spec's y wins, the preset's size stays
    cap = out["captions"]
    assert cap["max_words"] == 4 and cap["keywords"] == {"scale": 1.4, "words": ["90%", "Aisya"]}
    handle, = out["texts"]
    assert (handle["text"], handle["end"], handle["track"]) == ("@dr.aisya", "end", "brand")
    logo, = out["overlays"]
    assert logo["track"] == "logo" and logo["fit"] == "contain" and logo["end"] == "end"
    # the spec's own look is kept, and the preset's look-only keywords (no words) add nothing
    presets.save("plain", {"look": "talk", "captions": {"keywords": {"scale": 1.3}}})
    out = presets.apply(spec_for(media, preset="plain", look="clean", captions={"words": []}))
    assert out["look"] == "clean" and "keywords" not in out["captions"]


def test_the_builder_takes_a_preset(aisya, media):
    b = Builder(spec_for(media, preset=aisya), media.parent, allow_pro=True)
    b.build()
    assert not b.errors, b.errors
    names = {t.name for t in b.script.tracks.values()}
    assert {"brand", "logo"} <= names
    with pytest.raises(SpecError, match="no preset"):
        Builder(spec_for(media, preset="nobody"), media.parent, allow_pro=True)


def test_from_spec_keeps_the_series_and_drops_the_video(media):
    spec = spec_for(media, look="edu", brand={"accent": "#14B8A6"}, styles={"caption": {"y": -0.31}},
                    captions={"words": [{"word": "a", "start": 0, "end": 1}], "max_words": 3,
                              "keywords": {"words": ["90%"], "color": "$accent"}})
    p = presets.from_spec(spec)
    assert p == {"look": "edu", "brand": {"accent": "#14B8A6"},
                 "captions": {"max_words": 3, "keywords": {"color": "$accent"}}}


def test_cli_save_show_list_delete(media, cappus_home):
    res = run("presets.py", "save", "kajian", "--look", "talk", "--handle", "@kajian",
              "--logo", media / "photo.png", "--description", "kajian subuh")
    assert res.returncode == 0, res.stderr
    saved = json.loads(res.stdout)["preset"]
    assert saved["logo"]["src"] == str((media / "photo.png").resolve())
    listed = json.loads(run("presets.py").stdout)["presets"]
    assert listed == [{"name": "kajian", "look": "talk", "description": "kajian subuh"}]
    assert run("presets.py", "save", "x", "--logo", "missing.png").returncode == 2
    assert run("presets.py", "save", "kajian", "--accent", "#FF0000").returncode == 0
    assert json.loads(run("presets.py", "show", "kajian").stdout)["look"] == "talk"
    assert run("presets.py", "delete", "kajian").returncode == 0
    assert run("presets.py", "show", "kajian").returncode == 2


def test_cut_talk_takes_its_defaults_from_a_preset(aisya, talk):  # noqa: F811
    report, spec = cut(talk, "--preset", aisya)
    assert spec["preset"] == aisya and spec["look"] == "edu"
    name, role = [t for t in spec["texts"] if t.get("track") == "lower_third"]
    assert (name["text"], role["text"]) == ("dr. Aisya", "Dokter Umum")
    assert spec["captions"]["max_words"] == 2
    # a flag given on the command line beats the preset
    _, spec = cut(talk, "--preset", aisya, "--speaker", "dr. Hans", "--look", "talk")
    assert spec["look"] == "talk"
    assert [t["text"] for t in spec["texts"] if t.get("track") == "lower_third"][0] == "dr. Hans"
    check = run("build_draft.py", talk.parent / "talk.cut.json", "--check")
    assert check.returncode == 0, check.stdout + check.stderr
    assert run("cut_talk.py", talk, "--preset", "nobody").returncode != 0

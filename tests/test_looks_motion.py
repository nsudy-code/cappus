"""Looks, curated fonts, motion presets, text-fit warnings, generated music and website capture."""
import json
import wave

import pytest

import _common
import looks
import motion
import site_capture
from conftest import SCRIPTS, run


def check(tmp_path, spec):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return run("build_draft.py", path, "--check")


def report(res):
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def clip(media, seconds=4):
    return [{"src": str(media / "vertical.mp4"), "duration": seconds}]


# ---------- curated fonts and looks only use free items CapCut loads ----------

def test_curated_fonts_are_free_and_resolve():
    for alias, info in _common.curated_fonts().items():
        member = _common.resolve("font", alias)  # raises for Pro or withdrawn items
        assert member.name == info["name"], alias
        assert info["role"] in ("headline", "body", "script"), alias
        assert 1.0 < info["width"] < 7.0, alias


LOOK_REFS = {"transitions": "transition"}


@pytest.mark.parametrize("name", sorted(looks.looks()))
def test_look_resources_are_free_and_resolve(name):
    lk = looks.looks()[name]
    for t in lk["transitions"]:
        _common.resolve("transition", t)
    if lk["hit"]:
        _common.resolve("scene_effect", lk["hit"]["effect"])
    if lk["filter"]:
        _common.resolve("filter", lk["filter"]["name"])
    for font in lk["fonts"].values():
        assert font in _common.curated_fonts(), (name, font)
    assert lk["music"]["mood"] in ("hype", "corporate", "chill", "cinematic")


@pytest.mark.parametrize("name", sorted(looks.looks()))
def test_every_look_style_builds(tmp_path, media, name):
    texts = [{"text": "HELLO", "at": i * 0.5, "duration": 1.5, "style": st, "y": 0.6 - i * 0.2}
             for i, st in enumerate(("title", "accent", "big", "label"))]
    spec = {"look": name, "brand": {"accent": "#F59E0B"}, "video": clip(media), "texts": texts,
            "captions": {"cues": [{"start": 0.5, "end": 2.0, "text": "a caption"}]}}
    rep = report(check(tmp_path, spec))
    assert any("captions" in row for row in rep["timeline"])


def test_brand_color_replaces_the_look_accent():
    st = looks.styles("clean_tech", {"accent": "#F59E0B"})
    assert st["accent"]["color"] == "#F59E0B"
    assert st["title"]["color"] == looks.looks()["clean_tech"]["colors"]["text"]


def test_spec_styles_override_the_look_key_by_key(tmp_path, media):
    import build_draft
    styles = build_draft.Builder.resolve_styles({"look": "bold_promo", "styles": {"title": {"size": 9}, "mine": {"size": 5}}})
    assert styles["title"]["size"] == 9 and styles["title"]["font"] == "anton"
    assert styles["mine"] == {"size": 5}


@pytest.mark.parametrize("spec, message", [
    ({"look": "nope"}, "unknown look 'nope'"),
    ({"brand": {"accent": "#FFFFFF"}}, "only applies together with spec.look"),
    ({"look": "clean_tech", "brand": {"accent": "orange"}}, "spec.brand.accent must be '#RRGGBB'"),
    ({"look": "clean_tech", "brand": {"primary": "#FFFFFF"}}, "unknown key(s) ['primary']"),
])
def test_bad_look_or_brand(tmp_path, media, spec, message):
    res = check(tmp_path, {**spec, "video": clip(media)})
    assert res.returncode == 1 and message in res.stderr, res.stderr


# ---------- motion presets ----------

REST = {"x": 0.2, "y": -0.1, "scale": 0.7, "opacity": 1.0}


@pytest.mark.parametrize("name", sorted(motion.ENTER))
def test_every_enter_preset_ends_at_rest(name):
    pts = motion.enter_points(name, 0.4, REST, "overlay", width=0.5)
    for prop, points in pts.items():
        assert points[0][0] == 0 and 0 < points[-1][0] <= 0.4 + 1e-9  # fades may finish early
        times = [t for t, _ in points]
        assert times == sorted(times)
        rest = {"scale": REST["scale"], "scale_x": REST["scale"], "x": REST["x"], "y": REST["y"],
                "opacity": REST["opacity"], "rotation": 0.0}[prop]
        assert points[-1][1] == pytest.approx(rest, abs=1e-4), (name, prop)


@pytest.mark.parametrize("name", sorted(motion.EXIT))
def test_every_exit_preset_starts_at_rest(name):
    pts = motion.exit_points(name, 0.3, 2.0, REST, "overlay")
    for prop, points in pts.items():
        assert 1.7 - 1e-9 <= points[0][0] < 2.0 and points[-1][0] == pytest.approx(2.0)  # fades may start late
        rest = {"scale": REST["scale"], "x": REST["x"], "y": REST["y"], "opacity": REST["opacity"]}[prop]
        assert points[0][1] == pytest.approx(rest, abs=1e-4), (name, prop)


def test_grow_left_keeps_the_left_edge_still():
    w = 0.6
    pts = motion.enter_points("grow_left", 0.45, REST, "overlay", width=w)
    for (_, sx), (_, x) in zip(pts["scale_x"], pts["x"]):
        shown = w * sx / REST["scale"]
        assert x - shown / 2 == pytest.approx(REST["x"] - w / 2, abs=1e-4)


def test_enter_merges_into_a_drift_without_a_jump():
    drift = [[0, 0.7], [4.0, 0.728]]
    pop = motion.enter_points("pop", 0.35, REST, "overlay")["scale"]
    merged = motion.merge(drift, pop, (0, 0.35), "enter")
    assert merged[-1] == [4.0, 0.728]
    at_end = [v for t, v in merged if t == pytest.approx(0.35)][0]
    assert at_end == pytest.approx(motion.value_at(drift, 0.35), abs=1e-4)


def draft_keyframes(tmp_path, spec):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({"name": "t-motion", **spec}), encoding="utf-8")
    drafts = tmp_path / "drafts"
    drafts.mkdir(exist_ok=True)
    res = run("build_draft.py", path, "--drafts-dir", drafts)
    assert res.returncode == 0, res.stderr
    data = json.loads((drafts / "t-motion" / "draft_content.json").read_text(encoding="utf-8"))
    out = {}
    for t in data["tracks"]:
        for s in t["segments"]:
            for k in s.get("common_keyframes") or []:
                out.setdefault((t["type"], round(s["target_timerange"]["start"] / 1e6, 2)), set()).add(k["property_type"])
    return out


def test_presets_reach_the_draft(tmp_path, media):
    spec = {"video": clip(media),
            "overlays": [{"src": str(media / "photo.png"), "at": 0.5, "duration": 2, "enter": "pop", "exit": "fade",
                          "transform": {"scale": 0.5}, "keyframes": {"scale": [[0, 0.5], [2, 0.52]]}},
                         {"src": str(media / "photo.png"), "at": 2.5, "duration": 1, "enter": "grow_left",
                          "transform": {"scale": 0.3, "x": 0.2}}],
            "texts": [{"text": "HI", "at": 1, "duration": 1, "enter": "rise", "exit": "shrink"}]}
    kfs = draft_keyframes(tmp_path, spec)
    assert {"KFTypeAlpha"} <= kfs[("video", 0.5)]
    assert {"KFTypeScaleX", "KFTypePositionX"} <= kfs[("video", 2.5)]
    assert {"KFTypePositionY"} <= kfs[("text", 1.0)]


@pytest.mark.parametrize("item, message", [
    ({"enter": "fade"}, "no enter preset 'fade' for texts"),
    ({"enter": "zoomy"}, "no enter preset 'zoomy'"),
    ({"exit": {"name": "sink", "duration": -1}}, "exit.duration must be more than 0"),
])
def test_bad_presets_get_a_clear_message(tmp_path, media, item, message):
    res = check(tmp_path, {"video": clip(media), "texts": [{"text": "HI", "at": 0, "duration": 1, **item}]})
    assert res.returncode == 1 and message in res.stderr, res.stderr


# ---------- text fit ----------

def test_a_line_too_wide_for_the_wrap_width_is_warned(tmp_path, media):
    spec = {"video": clip(media), "texts": [
        {"text": "COMPANY PROFILES AND MORE", "at": 0, "duration": 1, "font": "bungee", "size": 14},
        {"text": "SHORT", "at": 1, "duration": 1, "font": "bungee", "size": 14}]}
    warnings = report(check(tmp_path, spec))["warnings"]
    assert len(warnings) == 1 and warnings[0].startswith("texts[0]") and "wraps onto another line" in warnings[0]


def test_the_lux_promo_sizes_fit(tmp_path, media):
    """Line lengths and sizes from the lux.ai.id promo, which looked right in CapCut."""
    texts = [{"text": t, "at": i, "duration": 1, "font": "poppins_bold", "size": s, "bold": True}
             for i, (t, s) in enumerate((("COMPANY PROFILES", 15), ("FIXED PRICE FROM", 12), ("IDR 3,000,000", 15)))]
    assert report(check(tmp_path, {"video": clip(media), "texts": texts}))["warnings"] == []


# ---------- generated music ----------

def test_music_writes_audio_and_an_exact_beat_map(tmp_path):
    out = tmp_path / "m.wav"
    res = run("music.py", out, "--mood", "corporate", "--bpm", "120", "--length", "8", "--drop", "2")
    assert res.returncode == 0, res.stderr
    with wave.open(str(out)) as w:
        assert w.getframerate() == 44100 and abs(w.getnframes() / 44100 - 8) < 0.01
    beats = json.loads(out.with_suffix(".beats.json").read_text(encoding="utf-8"))
    assert beats["beat"] == 0.5 and beats["beats"][:3] == [0.0, 0.5, 1.0] and beats["downbeats"][1] == 2.0
    assert [s["name"] for s in beats["sections"]] == ["intro", "drop"]


@pytest.mark.parametrize("args, message", [
    (["--bpm", "300"], "--bpm must be between 60 and 180"),
    (["--length", "8", "--drop", "20"], "--drop 20.0s is outside the track"),
    (["--length", "30", "--drop", "4", "--breath", "2"], "--breath must come after the drop"),
])
def test_music_rejects_bad_arguments(tmp_path, args, message):
    res = run("music.py", tmp_path / "m.wav", *args)
    assert res.returncode == 2 and message in res.stderr, res.stderr


# ---------- website capture (the part that needs no browser) ----------

def test_site_summary_finds_claims_contacts_and_brand_colors():
    raw = {"title": "Acme", "description": "We build sites", "lang": "en", "h1": ["Talk to the developer."],
           "buttons": ["Chat on WhatsApp"], "paragraphs": [],
           "links": ["https://wa.me/62811822677", "https://instagram.com/acme", "https://acme.id/blog"],
           "body_bg": "#090D16", "body_color": "#F8FAFC",
           "button_bgs": ["#F59E0B", "#F59E0B", "#0F172A", "#F59E0B"], "heading_colors": ["#F8FAFC"],
           "full_text": "Landing IDR 3,000,000 Business IDR 5,000,000 mail sud@acme.id WhatsApp 0811 822 677"}
    site = site_capture.summarize(raw, "https://acme.id")
    assert site["colors"]["accent"] == "#F59E0B" and site["colors"]["dark"] is True
    assert site["prices"] == ["IDR 3,000,000", "IDR 5,000,000"]
    assert site["contact"]["emails"] == ["sud@acme.id"]
    assert site["contact"]["phones"] == ["0811 822 677"]
    assert site["contact"]["whatsapp_links"] == ["https://wa.me/62811822677"]
    assert site["contact"]["socials"] == ["https://instagram.com/acme"]


def test_looks_cli_lists_every_look():
    res = run("looks.py")
    assert res.returncode == 0
    for name in looks.looks():
        assert name in res.stdout


# ---------- kinetic typography helpers ----------

def texts_in_draft(tmp_path, spec):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({"name": "t-kinetic", **spec}), encoding="utf-8")
    drafts = tmp_path / "drafts"
    drafts.mkdir(exist_ok=True)
    res = run("build_draft.py", path, "--drafts-dir", drafts)
    assert res.returncode == 0, res.stderr
    data = json.loads((drafts / "t-kinetic" / "draft_content.json").read_text(encoding="utf-8"))
    mats = {m["id"]: m for m in data["materials"]["texts"]}
    out = []
    for t in data["tracks"]:
        if t["type"] != "text":
            continue
        for seg in t["segments"]:
            content = json.loads(mats[seg["material_id"]]["content"])
            size = content["styles"][0].get("size")
            kfs = {k["property_type"]: [kf["values"][0] for kf in k["keyframe_list"]] for k in seg.get("common_keyframes") or []}
            out.append({"text": content["text"], "at": seg["target_timerange"]["start"] / 1e6, "size": size, "kf": kfs})
    return sorted(out, key=lambda r: r["at"])


def test_fit_width_makes_short_words_big_and_long_words_fit(tmp_path, media):
    spec = {"look": "kinetic", "video": clip(media),
            "texts": [{"text": "BLOG", "at": 0, "duration": 1, "style": "word"},
                      {"text": "DASHBOARD", "at": 1, "duration": 1, "style": "word"}]}
    rep = report(check(tmp_path, spec))
    assert rep["warnings"] == []
    rows = texts_in_draft(tmp_path, spec)
    blog, dash = rows[0]["size"], rows[1]["size"]
    assert blog == 40 and dash < 30, (blog, dash)  # a short word is capped by the look's size_max
    k = _common.curated_fonts()["coda_heavy"]["width"]
    assert 9 * k * dash * 1.15 == pytest.approx(0.86 * 1080, rel=0.02)


def test_echo_repeats_the_word_with_a_stagger(tmp_path, media):
    spec = {"look": "kinetic", "video": clip(media),
            "texts": [{"text": "WEBSITE?", "at": 1.0, "end": 2.0, "style": "word", "echo": {"count": 4, "stagger": 0.08}}]}
    rows = texts_in_draft(tmp_path, spec)
    assert [r["text"] for r in rows] == ["WEBSITE?"] * 5
    assert [round(r["at"], 2) for r in rows] == [1.0, 1.08, 1.16, 1.24, 1.32]
    assert len({r["size"] for r in rows}) == 1


def test_drift_and_kinetic_presets_reach_the_draft(tmp_path, media):
    spec = {"video": clip(media), "texts": [
        {"text": "GO", "at": 0, "duration": 1, "size": 20, "drift": 0.05, "enter": "slam", "exit": "zoom_through"},
        {"text": "UP", "at": 1, "duration": 1, "size": 20, "rotation": 8, "enter": "spin"}]}
    go, up = texts_in_draft(tmp_path, spec)
    scale = go["kf"]["UNIFORM_SCALE"] if "UNIFORM_SCALE" in go["kf"] else go["kf"]["KFTypeScaleX"]
    assert scale[0] == pytest.approx(1.9) and max(scale) == pytest.approx(14 * 1.0 * (1 + 0.05 * 0.74), rel=0.05)
    assert up["kf"]["KFTypeRotation"][0] == pytest.approx(8 - 120) and up["kf"]["KFTypeRotation"][-1] == pytest.approx(8)


def test_letter_spacing_counts_toward_the_fit(tmp_path, media):
    """Measured in CapCut 9.8: these two lines, with the cinematic look's spacing."""
    spec = {"video": clip(media), "texts": [
        {"text": "SUMMER", "at": 0, "duration": 1, "font": "cinzel", "size": 26, "letter_spacing": 6},
        {"text": "NEXT SUMMER", "at": 1, "duration": 1, "font": "cinzel", "size": 18, "letter_spacing": 4}]}
    warnings = report(check(tmp_path, spec))["warnings"]
    assert len(warnings) == 1 and warnings[0].startswith("texts[1]") and "wraps" in warnings[0], warnings


# ---------- footage: scan, adjust, motion around the transform ----------

def test_scan_finds_the_bad_copies_and_keeps_the_good_one(tmp_path, media):
    import shutil
    import subprocess
    folder = tmp_path / "clips"
    folder.mkdir()
    shutil.copy(media / "landscape.mp4", folder / "good.mp4")
    for name, vf in (("blurry.mp4", "gblur=sigma=8"), ("dark.mp4", "eq=brightness=-0.45")):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(media / "landscape.mp4"), "-vf", vf, "-an",
                        str(folder / name)], check=True)
    res = run("scan_footage.py", folder, "--out", tmp_path / "scan")
    assert res.returncode == 0, res.stderr
    rep = json.loads((tmp_path / "scan" / "footage.json").read_text(encoding="utf-8"))
    assert [s["name"] for s in rep["ranked"]][0] == "good.mp4"
    dupes = {s["name"]: s for s in rep["duplicates"]}
    assert set(dupes) == {"blurry.mp4", "dark.mp4"}, [s["name"] for s in rep["ranked"]]
    assert any("blurry" in r for r in dupes["blurry.mp4"]["reasons"])
    good_exposure = rep["ranked"][0]["stats"]["exposure"]
    assert dupes["dark.mp4"]["stats"]["exposure"] < good_exposure - 0.1
    good = rep["ranked"][0]
    assert good["in"] <= good["best"]["in"] < good["best"]["out"] <= good["out"]
    assert good["text_y"] in (0.5, 0.0, -0.5)
    assert (tmp_path / "scan" / "best.jpg").is_file()


def test_adjust_and_motion_keep_the_clip_transform(tmp_path, media):
    spec = {"name": "t-adjust", "video": [{"src": str(media / "landscape.mp4"), "duration": 2, "fit": "cover",
                                           "adjust": {"brightness": -0.1, "saturation": 0.08},
                                           "transform": {"x": 0.4}, "motion": {"type": "pan_left", "amount": 0.06}}]}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    res = run("build_draft.py", path, "--drafts-dir", drafts)
    assert res.returncode == 0, res.stderr
    data = json.loads((drafts / "t-adjust" / "draft_content.json").read_text(encoding="utf-8"))
    seg = next(t for t in data["tracks"] if t["type"] == "video")["segments"][0]
    kf = {k["property_type"]: [x["values"][0] for x in k["keyframe_list"]] for k in seg["common_keyframes"]}
    assert kf["KFTypeBrightness"] == [pytest.approx(-0.1)] * 2
    assert kf["KFTypeSaturation"] == [pytest.approx(0.08)] * 2
    assert kf["KFTypePositionX"][0] == pytest.approx(0.46) and kf["KFTypePositionX"][-1] == pytest.approx(0.34)


def test_adjust_conflicts_with_keyframes_on_the_same_property(tmp_path, media):
    res = check(tmp_path, {"video": [{"src": str(media / "landscape.mp4"), "duration": 2, "adjust": {"brightness": 0.1},
                                      "keyframes": {"brightness": [[0, 0], [1, 0.2]]}}]})
    assert res.returncode == 1 and "adjust and keyframes both set 'brightness'" in res.stderr, res.stderr


# ---------- suggest: fit the theme and the footage, and differ from the last edits ----------

@pytest.mark.parametrize("theme, look", [
    ("bikin video promo website saya", "kinetic"),
    ("promo villa mewah", "luxury"),
    ("flash sale produk baru", "bold_promo"),
    ("jualan kopi di cafe", "playful"),
    ("liburan ke pantai", "cinematic"),
])
def test_suggest_matches_the_theme(theme, look):
    assert looks.suggest(theme, seed=1)["spec"]["look"] == look


def test_suggest_with_footage_and_no_theme_starts_from_cinematic():
    scan = {"palette": {"accent": "#61CCFF", "pace": "low", "light": {"day": 5}}}
    choice = looks.suggest("", scan=scan, seed=1)
    assert choice["spec"]["look"] == "cinematic" and choice["spec"]["brand"] == {"accent": "#61CCFF"}


def test_brand_accent_wins_over_the_footage():
    scan = {"palette": {"accent": "#61CCFF", "pace": "low", "light": {"day": 5}}}
    assert looks.suggest("liburan", scan=scan, brand_accent="#F59E0B", seed=1)["spec"]["brand"]["accent"] == "#F59E0B"


def test_suggest_never_repeats_the_last_two_edits(cappus_home):
    seen = []
    for _ in range(6):
        choice = looks.suggest("liburan ke pantai", seed=None, history=looks.load_history())
        looks.record(choice)
        seen.append(choice["spec"]["fonts"]["headline"])
    for a, b, c in zip(seen, seen[1:], seen[2:]):
        assert c not in (a, b), seen
    assert len(set(seen)) >= 3


def test_spec_fonts_swap_the_pairing_and_scale_sizes(tmp_path, media):
    spec = {"look": "cinematic", "fonts": {"headline": "sequel_wide", "body": "dm_sans_italic"}, "video": clip(media),
            "texts": [{"text": "SUMMER", "at": 0, "duration": 1, "style": "title"}]}
    rows = texts_in_draft(tmp_path, spec)
    base = looks.looks()["cinematic"]["styles"]["title"]["size"]
    ratio = _common.curated_fonts()["anton"]["width"] / _common.curated_fonts()["sequel_wide"]["width"]
    assert rows[0]["size"] == pytest.approx(base * max(0.4, min(1.5, ratio)), abs=0.2)  # the ratio is capped


def test_spec_fonts_must_be_curated(tmp_path, media):
    res = check(tmp_path, {"look": "cinematic", "fonts": {"headline": "comic_sans"}, "video": clip(media)})
    assert res.returncode == 1 and "not in fonts.json" in res.stderr, res.stderr


def test_every_pairing_uses_curated_fonts():
    for name, lk in looks.looks().items():
        for pr in lk.get("pairings", []):
            assert pr["headline"] in _common.curated_fonts() and pr["body"] in _common.curated_fonts(), (name, pr)

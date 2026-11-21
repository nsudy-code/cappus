"""Loudness levelling: every audible clip and audio item brought to one LUFS target."""
import subprocess
from pathlib import Path

import pytest

import probe
from build_draft import Builder, SpecError
from test_cut_talk import cut, talk  # noqa: F401  (the synthetic take fixture)


def tone(path: Path, gain_db: float, seconds=4) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-af", f"volume={gain_db}dB", str(path)], check=True)
    return path


@pytest.fixture
def tones(tmp_path):
    return {"quiet": tone(tmp_path / "quiet.wav", 0), "loud": tone(tmp_path / "loud.wav", 15),
            "silent": tone(tmp_path / "silent.wav", -200)}


def build(media, **spec):
    b = Builder(dict({"video": [{"src": str(media / "vertical.mp4"), "duration": 4, "mute": True}]}, **spec),
                media.parent, allow_pro=True)
    b.build()
    assert not b.errors, b.errors
    segs = {Path(s.material_instance.path).stem: s for t in b.script.tracks.values()
            if t.track_type.name == "audio" for s in t.segments}
    return b, segs


def test_probe_measures_lufs_and_peak(tones):
    q, ld = probe.loudness(tones["quiet"]), probe.loudness(tones["loud"])
    assert -23 < q["lufs"] < -19 and -19 < q["peak_db"] < -17
    assert ld["lufs"] == pytest.approx(q["lufs"] + 15, abs=0.5)
    assert probe.loudness(tones["silent"]) is None


def test_audio_is_raised_or_lowered_to_the_target(media, tones):
    b, segs = build(media, loudness=True, audio=[
        {"src": str(tones["quiet"]), "track": "voice"},
        {"src": str(tones["loud"]), "volume": 0.5, "keyframes": {"volume": [[0, 0.5], [2, 1.0]]}},
        {"src": str(tones["silent"])},
    ])
    rows = {r["file"]: r for r in b.report()["loudness"]["files"]}
    assert rows["quiet.wav"]["now_lufs"] == pytest.approx(-14, abs=0.2) and "held_by_peak" not in rows["quiet.wav"]
    assert rows["loud.wav"]["gain_db"] < -7 and "silent.wav" not in rows
    quiet, loud, silent = segs["quiet"], segs["loud"], segs["silent"]
    gain_q = 10 ** (rows["quiet.wav"]["gain_db"] / 20)
    gain_l = 10 ** (rows["loud.wav"]["gain_db"] / 20)
    assert quiet.volume == pytest.approx(gain_q, abs=0.01)
    assert loud.volume == pytest.approx(0.5 * gain_l, abs=0.01)  # the spec's own volume still counts
    kf_values = [k.values[0] for kl in loud.common_keyframes for k in kl.keyframes]
    assert kf_values == pytest.approx([0.5 * gain_l, gain_l], abs=0.01)
    assert silent.volume == 1.0
    assert sorted(v for _, _, v in b.music) == [0.5, 1.0]  # sfx follow the spec's level, not the gain


def test_a_peak_caps_the_raise_but_never_lowers(media, tones):
    b, _ = build(media, loudness={"target": -5, "peak": -10}, audio=[{"src": str(tones["quiet"])}])
    row, = b.report()["loudness"]["files"]
    assert row["held_by_peak"] and row["gain_db"] == pytest.approx(-10 - row["peak_db"], abs=0.11)
    # the loud tone is a little under -5 LUFS, but its peak is already over -10: it stays as it is
    b, _ = build(media, loudness={"target": -5, "peak": -10}, audio=[{"src": str(tones["loud"])}])
    assert b.report()["loudness"]["files"][0]["gain_db"] == 0.0
    assert "Normalize loudness" in b.report()["loudness"]["hint"]


def test_off_by_default_and_per_item(media, tones):
    b, segs = build(media, audio=[{"src": str(tones["quiet"])}])
    assert segs["quiet"].volume == 1.0 and "loudness" not in b.report()
    b, segs = build(media, loudness=-14, audio=[{"src": str(tones["quiet"]), "loudness": False}])
    assert segs["quiet"].volume == 1.0
    with pytest.raises(SpecError, match="LUFS"):
        Builder({"loudness": "loud", "video": []}, media.parent)


def test_cut_talk_levels_the_speech(talk):  # noqa: F811
    report, spec = cut(talk)
    assert spec["loudness"] == -14
    _, spec = cut(talk, "--no-loudness")
    assert "loudness" not in spec


@pytest.fixture
def model(monkeypatch):
    import build_draft
    monkeypatch.setattr(build_draft, "denoise_model", lambda: "C:/CapCut/Apps/9.8/Resources/audiosami/m.model")


def test_denoise_switches_on_reduce_noise(media, tones, model):
    b, segs = build(media, audio=[{"src": str(tones["quiet"]), "denoise": True},
                                  {"src": str(tones["loud"]), "denoise": 0.5}, {"src": str(tones["silent"])}])
    mats = {m["id"]: m for m in b.script.imported_materials["realtime_denoises"]}
    assert len(mats) == 2 and not set(mats) & set(segs["silent"].extra_material_refs)
    quiet = mats[segs["quiet"].extra_material_refs[-1]]
    assert (quiet["type"], quiet["is_denoise"], quiet["denoise_rate"]) == ("realtime_denoise", True, 0.85)
    assert quiet["path"].endswith("m.model") and mats[segs["loud"].extra_material_refs[-1]]["denoise_rate"] == 0.5
    assert "feature: denoise (Reduce noise)" in b.report()["pro_resources"]


def test_denoise_needs_pro_and_capcut(media, tones, model, monkeypatch):
    spec = {"video": [{"src": str(media / "vertical.mp4"), "duration": 4, "denoise": True}]}
    b = Builder(spec, media.parent, allow_pro=False)
    b.build()
    assert "Pro" in b.errors[0]
    import build_draft
    monkeypatch.setattr(build_draft, "denoise_model", lambda: None)
    b = Builder(spec, media.parent, allow_pro=True)
    b.build()
    assert "Reduce noise" in b.errors[0]


def test_cut_talk_denoise_flag(talk):  # noqa: F811
    _, spec = cut(talk, "--denoise")
    assert all(v.get("denoise") for v in spec["video"])

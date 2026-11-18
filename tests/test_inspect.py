"""inspect_draft.py and check_resources.py find a draft by its name."""
import json
from pathlib import Path

from conftest import run
from _env import draft_folder


def test_bare_name_means_the_capcut_draft_even_with_a_local_folder_of_that_name(tmp_path, media):
    """Claude usually works in the user's project folder, which is often named like the draft."""
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"name": "Trip", "video": [{"src": str(media / "vertical.mp4"), "duration": 2}]}),
                    encoding="utf-8")
    res = run("build_draft.py", spec, "--drafts-dir", drafts)
    assert res.returncode == 0, res.stderr
    work = tmp_path / "work"
    (work / "Trip").mkdir(parents=True)
    res = run("inspect_draft.py", "Trip", "--drafts-dir", drafts, cwd=work)
    assert res.returncode == 0, res.stderr
    report = json.loads(res.stdout)
    assert Path(report["file"]).parent == drafts / "Trip"
    assert report["edited_in_capcut_since_build"] is False


def test_draft_folder_lookup_order(tmp_path, monkeypatch):
    drafts = tmp_path / "drafts"
    (drafts / "a").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a").mkdir()
    (tmp_path / "only-here").mkdir()
    assert draft_folder("a", drafts) == drafts / "a"                       # a bare name: the draft first
    assert draft_folder("./a", drafts) == Path("a")                        # a path: the path first
    assert draft_folder(str(tmp_path / "a"), drafts) == tmp_path / "a"
    assert draft_folder("only-here", drafts) == Path("only-here")          # no such draft: the local folder
    assert draft_folder("missing", drafts) is None
    assert draft_folder("a", None) == Path("a")                            # no drafts folder found
    assert draft_folder("..", drafts) == Path("..")

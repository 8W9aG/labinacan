"""The literature map's queue, its report and the check that each review is on it.

None of these needs the map extra (labinacan/literature_map_io.py).
"""

import hashlib
import json
import subprocess

from labinacan import config as cfg
from labinacan import literature_map_io as io
from labinacan.site.literature_pages import LITERATURE, MAP, map_text


def _project(root, mapped=("a",), sha=None):
    """A project with reviews a and b, the index and a queue page, and a map of ``mapped``."""
    folder = root / LITERATURE
    folder.mkdir(parents=True)
    (folder / "README.md").write_text("# Literature review\n\n- [A](a.md)\n- [B](b.md)\n")
    (folder / "queue.md").write_text("# Queue\n\nNothing yet.\n")
    for name in "ab":
        (folder / f"{name}.md").write_text(f"# Paper {name}\n\n## Summary\n\nAbout {name}.\n")
    rows = [{"name": name, "x": 0.5, "y": 0.5,
             "sha256": sha or hashlib.sha256(map_text(folder / f"{name}.md").encode()).hexdigest()}
            for name in mapped]  # fmt: skip
    (folder / MAP).write_text(json.dumps({"model": "m", "reviews": rows}))
    return folder


def test_a_review_not_on_the_map_is_missing(tmp_path):
    _project(tmp_path)
    assert io.missing_from_map(tmp_path) == ["b"]  # the index and the queue never are


def test_every_review_on_the_map_leaves_none_missing(tmp_path):
    _project(tmp_path, mapped=("a", "b"))
    assert io.missing_from_map(tmp_path) == []


def test_a_review_changed_since_the_map_is_missing(tmp_path):
    _project(tmp_path, mapped=("a", "b"), sha="0" * 64)
    assert io.missing_from_map(tmp_path) == ["a", "b"]


def test_a_project_with_no_reviews_misses_none(tmp_path):
    assert io.missing_from_map(tmp_path) == []


def test_the_queue_is_the_repos_open_issues_with_the_label(monkeypatch):
    seen = []
    issues = [
        {"number": 9, "title": "Review A paper", "body": "Source.\n\n**Bears on:** x.\n\nMore."},
        {"number": 3, "title": "B", "body": None},
    ]

    def run(args, **kwargs):
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(issues))

    monkeypatch.setattr(io.subprocess, "run", run)
    assert io.queued("o/r", "lit") == [
        {"number": 3, "title": "B", "text": "B"},
        {"number": 9, "title": "A paper", "text": "A paper\n\nx."},
    ]
    assert seen[0][:7] == ["gh", "issue", "list", "--repo", "o/r", "--label", "lit"]


def test_no_repo_or_no_gh_gives_no_queue(monkeypatch):
    def run(args, **kwargs):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(io.subprocess, "run", run)
    assert io.queued("o/r", "lit") == []
    assert io.queued("", "lit") == []  # gh is not run


def test_gh_failing_gives_no_queue(monkeypatch):
    def run(args, **kwargs):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(io.subprocess, "run", run)
    assert io.queued("o/r", "lit") == []


def test_the_queue_comes_from_the_projects_config(monkeypatch):
    c = cfg.config()
    assert io.queue_source() == (c.literature_repo, c.literature_label)
    assert (c.literature_repo, c.literature_label) == (c.repo, cfg.LITERATURE_LABEL)

    def no_table():
        raise LookupError("no [tool.labinacan] table")

    monkeypatch.setattr(io, "config", no_table)
    assert io.queue_source() == ("", "")

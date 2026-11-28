"""The literature map's generator (labinacan/literature_map.py) and its page check."""

import hashlib
import json
from collections import Counter

import pytest

from labinacan import literature_map as lm
from labinacan import literature_map_io as io
from labinacan.site.literature_pages import LITERATURE, MAP, map_text

np = pytest.importorskip("numpy")  # in the map extra; the base package needs none


def test_the_knn_graph_keeps_each_pair_once_with_its_best_cosine():
    vectors = np.eye(3)[[0, 0, 1, 2]].astype(float)  # papers 0 and 1 are the same text
    edges = lm.knn_edges(vectors)
    assert edges[(0, 1)] == 1.0
    assert all(i < j for i, j in edges) and all(w >= 0 for w in edges.values())


def test_a_community_with_too_few_reviews_spreads_over_its_neighbours():
    # Papers 0–5 are reviews in communities 0 and 1. Queued papers 6 and 7 are community 2,
    # with no reviews, and each is tied to a different community.
    labels = [0, 0, 0, 1, 1, 1, 2, 2]
    edges = {(0, 6): 0.9, (3, 7): 0.9, (6, 7): 0.5}
    assert lm.merge_small(labels, edges, reviewed=6) == [0, 0, 0, 1, 1, 1, 0, 1]


def test_a_community_tied_to_nothing_joins_the_biggest():
    labels = [0, 0, 0, 1, 1, 1, 1, 2]
    assert lm.merge_small(labels, {}, reviewed=7) == [0, 0, 0, 1, 1, 1, 1, 1]


def test_a_paper_tied_only_inside_waits_for_its_neighbour_to_move():
    labels = [0, 0, 0, 1, 1]  # 3 and 4 are queued; only 3 is tied outside
    assert lm.merge_small(labels, {(0, 3): 0.8, (3, 4): 0.9}, reviewed=3) == [0] * 5


def test_one_community_is_left_as_it_is():
    assert lm.merge_small([0, 0, 0], {}, reviewed=1) == [0, 0, 0]


def test_a_region_that_smoothing_left_without_reviews_joins_its_nearest():
    # smoothing moved every review out of a community, which left it with no name.
    points = np.array(
        [[0.0, 0], [0.1, 0], [0.2, 0], [5, 0], [5.1, 0], [5.2, 0], [0.3, 0], [5.3, 0]]
    )
    labels = [0, 0, 0, 1, 1, 1, 2, 2]  # region 2 holds only the two queued papers
    assert lm.absorb_small(points, labels, reviewed=6) == [0, 0, 0, 1, 1, 1, 0, 1]
    assert lm.absorb_small(points, [0] * 8, reviewed=1) == [0] * 8


def test_a_region_no_section_can_name_joins_its_nearest(monkeypatch):
    # a small region whose sections bigger regions took is merged, not named "Region n".
    points = np.array([[0.0, 0], [0.1, 0], [5, 0], [5.1, 0], [0.2, 0]])
    seen = []

    def regions(points, labels, names, reviewed):
        seen.append(list(labels))
        rows = [
            {"number": n, "name": "A" if n == 1 else f"Region {n}"} for n in sorted(set(labels))
        ]
        return list(labels), rows

    monkeypatch.setattr(lm, "regions", regions)
    region_of, rows = lm.named_regions(points, [1, 1, 1, 1, 2], [], reviewed=4)
    assert region_of == [1, 1, 1, 1, 1] and seen == [[1, 1, 1, 1, 2], [1, 1, 1, 1, 1]]
    order = np.array([[0, 1, 2], [1, 0, 2], [2, 1, 0]])  # each point's points, nearest first
    assert lm.merge_region(order, [1, 2, 2], 2) == [1, 1, 1]


def test_smoothing_gives_a_stray_point_its_neighbours_region():
    rng = np.random.default_rng(0)
    left, right = rng.normal(0, 0.05, (10, 2)), rng.normal(1, 0.05, (10, 2))
    points = np.vstack([left, right])
    labels = [0] * 10 + [1] * 10
    labels[3] = 1  # a point of the left cloud labelled as the right
    assert lm.compactness(points, labels) == 0.95
    smoothed = lm.smooth(points, labels)
    assert smoothed == [0] * 10 + [1] * 10
    assert lm.compactness(points, smoothed) == 1.0


def test_regions_touch_where_their_points_are_neighbours():
    points = np.array([[0, 0], [0, 0.1], [0.2, 0], [5, 5], [5, 5.1], [5.2, 5]] * 2, dtype=float)
    labels = [1, 1, 1, 2, 2, 2, 1, 1, 3, 2, 2, 2]
    touches = lm.touching(points, labels)
    assert touches[1][3] > 0 and touches[3][1] == touches[1][3]


def test_a_tie_names_the_region_after_both_sections():
    taken = set()
    assert lm.region_name(Counter({"B": 2, "A": 2, None: 4}), taken) == "A · B"
    assert lm.region_name(Counter({"A": 3}), taken) == ""
    assert taken == {"A", "B"}


def test_the_issue_template_is_not_embedded():
    lead = "**Bears on:** the reviewer. Write a short not-applicable page."
    assert lm.plain_lead(lead) == "the reviewer."


def test_the_report_warns_when_the_regions_are_not_compact(capsys, tmp_path):
    data = {"reviews": [1], "queued": [], "regions": [1, 2], "compactness": 0.5,
            "layout": "umap seed 3"}  # fmt: skip
    lm.report(data, tmp_path / "map.json")
    out = capsys.readouterr()
    assert "1 reviews, 0 queued, 2 regions, compactness 0.5 (umap seed 3)" in out.out
    assert "Compactness is under" in out.err


def test_the_most_compact_seed_wins_and_a_tie_keeps_the_earlier():
    """One new page can reshuffle one seed's regions, so every seed is tried."""
    scores = {4577: 0.7, 1: 0.9, 2: 0.9, 3: 0.8}
    tried = []

    def build(vectors, names, reviewed, seed):
        tried.append((vectors, names, reviewed, seed))
        return seed, "points", "regions", "rows", scores[seed]

    best = lm.most_compact("v", ["a"], 1, seeds=(4577, 1, 2, 3), build=build)
    assert best == (1, "points", "regions", "rows", 0.9)
    assert tried == [("v", ["a"], 1, seed) for seed in (4577, 1, 2, 3)]
    assert lm.SEEDS[0] == 4577 and len(set(lm.SEEDS)) == len(lm.SEEDS)  # today's seed first


def _reviews(root, names="abcdef"):
    """Reviews under ``root``'s docs/literature/, in two README sections."""
    folder = root / LITERATURE
    folder.mkdir(parents=True)
    index = [
        "# Literature review",
        "",
        "## Topic A",
        "",
        "| Page | Status | Why |",
        "| - | - | - |",
    ]
    for i, name in enumerate(names):
        if i == len(names) // 2:
            index += ["", "## Topic B", "", "| Page | Status | Why |", "| - | - | - |"]
        index.append(f"| [{name.upper()}]({name}.md) (X, 2026) | used | Why. |")
        (folder / f"{name}.md").write_text(f"# Paper {name}\n\n## Summary\n\nAbout {name}.\n")
    (folder / "README.md").write_text("\n".join(index) + "\n")
    return folder


def test_main_embeds_the_reviews_and_the_queue_and_writes_the_map(monkeypatch, tmp_path, capsys):
    import sys
    import types

    folder = _reviews(tmp_path, "ab")
    monkeypatch.chdir(tmp_path)
    queue = [{"number": 7, "title": "A queued paper", "text": "A queued paper\n\nWhy."}]
    seen = {}

    class Model:
        def __init__(self, name, device):
            seen["model"] = (name, device)

        def encode(self, texts, normalize_embeddings):
            seen["texts"] = list(texts)
            return np.eye(3)

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(
        SentenceTransformer=Model))  # fmt: skip
    monkeypatch.setattr(lm, "queue_source", lambda: ("o/r", "lit"))
    monkeypatch.setattr(lm, "queued", lambda repo, label: seen.update(q=(repo, label)) or queue)
    points = np.array([[0.0, 0.0], [1.0, 1.0], [0.5, 0.5]])
    rows = [{"number": 1, "name": "Topic A", "x": 0.5, "y": 0.5, "size": 3, "touches": {}}]
    monkeypatch.setattr(lm, "most_compact", lambda v, n, r: (4577, points, [1, 1, 1], rows, 1.0))
    lm.main()
    data = json.loads((folder / MAP).read_text())
    assert seen["model"] == (lm.MODEL, "cpu") and seen["q"] == ("o/r", "lit")
    assert seen["texts"] == [map_text(folder / "a.md"), map_text(folder / "b.md"), queue[0]["text"]]
    assert [r["name"] for r in data["reviews"]] == ["a", "b"]
    assert data["reviews"][0]["sha256"] == hashlib.sha256(seen["texts"][0].encode()).hexdigest()
    assert data["reviews"][0]["neighbours"] == ["b"]  # never the review itself
    assert data["queued"] == [{"number": 7, "title": "A queued paper", "x": 0.5, "y": 0.5,
                               "region": 1}]  # fmt: skip
    assert (data["layout"], data["regions"]) == ("umap seed 4577", rows)
    assert "2 reviews, 1 queued, 1 regions" in capsys.readouterr().out
    assert io.missing_from_map(tmp_path) == []


def test_the_real_layout_names_each_region_after_a_section(monkeypatch, tmp_path):
    # Needs the map extra: UMAP, Leiden and igraph.
    for library in ("umap", "leidenalg", "igraph"):
        pytest.importorskip(library)
    _reviews(tmp_path, "abcdefghijkl")
    monkeypatch.chdir(tmp_path)
    rng = np.random.default_rng(0)
    vectors = rng.normal(size=(20, 8))
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    names = list("abcdefghijkl")
    seed, points, region_of, rows, compact = lm.most_compact(vectors, names, 12, seeds=(1,))
    assert seed == 1 and len(region_of) == 20 and 0 <= compact <= 1
    assert all(not r["name"].startswith("Region ") for r in rows)
    assert {r["number"] for r in rows} == set(region_of)


def test_one_review_sits_in_the_middle_with_no_neighbours():
    """A project with one review gets a map that is JSON: no NaN, and no self-neighbour."""
    assert lm.scaled(np.array([[3.0, -2.0]])).tolist() == [[0.5, 0.5]]
    assert lm.scaled(np.array([[0.0, 5.0], [2.0, 5.0], [1.0, 5.0]])).tolist() == [
        [0.0, 0.5], [1.0, 0.5], [0.5, 0.5]]  # fmt: skip
    assert lm.neighbours(np.eye(1), ["a"]) == [[]]
    vectors = np.array([[1.0, 0.0], [0.8, 0.6], [0.0, 1.0], [0.6, 0.8], [-1.0, 0.0]])
    assert lm.neighbours(vectors, list("abcde"))[0] == ["b", "d", "c"]

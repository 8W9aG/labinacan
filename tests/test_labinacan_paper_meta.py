"""Each paper's metadata file: ``CITATION.cff``, or the one that ``paper_meta`` names."""

import pytest

from labinacan import config as cfg
from labinacan.site import build as site_build
from labinacan.site.alphaxiv import alphaxiv_url
from labinacan.site.research import _read_paper, cff_authors
from tests.test_labinacan_config import PYPROJECT, restore  # noqa: F401  (a fixture)

META = (
    "authors:\n- given-names: Ada\n  family-names: Lovelace\n- name: A Project\n"
    "identifiers:\n- type: url\n  value: https://www.alphaxiv.org/abs/2611.00001\n"
    "  description: alphaXiv AI Track\n"
)
pytestmark = pytest.mark.usefixtures("restore")  # each test moves the config
NO_BRAND = PYPROJECT[: PYPROJECT.index("[tool.labinacan.brand]")]


def _use(tmp_path, extra: str = "") -> None:
    """Point the config at a project with no brand, and ``extra`` in [tool.labinacan]."""
    (tmp_path / "pyproject.toml").write_text(NO_BRAND + extra)
    cfg.use(tmp_path / "pyproject.toml")


def _paper(tmp_path, meta_file: str | None):
    """A papers/ folder with one listed paper, and its metadata in ``meta_file``."""
    papers = tmp_path / "papers"
    folder = papers / "p"
    folder.mkdir(parents=True)
    (papers / "README.md").write_text("# Papers\n\n- 2026-11-27: [P](p/README.md)\n")
    (folder / "README.md").write_text("# P\n\nA summary.\n\n## Results\n\nText.\n")
    if meta_file:
        (folder / meta_file).write_text(META)
    return papers, folder


def test_the_metadata_file_is_citation_cff_unless_the_project_names_another(tmp_path):
    _use(tmp_path)
    assert cfg.config().paper_meta == "CITATION.cff"
    _use(tmp_path, 'paper_meta = "paper.yml"\n')
    assert cfg.config().paper_meta == "paper.yml"


@pytest.mark.parametrize("meta_file", ["CITATION.cff", "paper.yml"])
def test_the_authors_and_the_alphaxiv_url_come_from_the_named_file(tmp_path, meta_file):
    _use(tmp_path, f'paper_meta = "{meta_file}"\n')
    _, folder = _paper(tmp_path, meta_file)
    assert cff_authors(folder) == ("Ada Lovelace", "A Project")
    assert alphaxiv_url(folder) == "https://www.alphaxiv.org/abs/2611.00001"


def test_a_citation_cff_is_not_read_when_the_project_names_paper_yml(tmp_path):
    _use(tmp_path, 'paper_meta = "paper.yml"\n')
    _, folder = _paper(tmp_path, "CITATION.cff")
    assert cff_authors(folder) == () and alphaxiv_url(folder) is None


def test_the_page_links_cite_only_to_a_citation_cff_that_exists(tmp_path):
    _use(tmp_path, 'paper_meta = "paper.yml"\n')
    papers, folder = _paper(tmp_path, "paper.yml")
    assert _read_paper(folder, "https://github.com/someone/a-project").citation is None
    site_build.build(tmp_path / "dist", templates=None, papers_dir=papers)
    page = (tmp_path / "dist" / "research" / "p" / "index.html").read_text()
    assert "Ada Lovelace, A Project" in page and ">Cite<" not in page

    _use(tmp_path)
    (folder / "CITATION.cff").write_text(META)
    assert _read_paper(folder, "https://github.com/someone/a-project").citation == "CITATION.cff"
    site_build.build(tmp_path / "dist2", templates=None, papers_dir=papers)
    page = (tmp_path / "dist2" / "research" / "p" / "index.html").read_text()
    assert '/blob/main/papers/p/CITATION.cff">Cite</a>' in page

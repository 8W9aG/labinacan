"""An installed labinacan reads the project's files from the folder the build runs in."""

from pathlib import Path

from labinacan.site import changelog_page, literature_pages


def test_the_project_paths_are_relative_to_the_working_folder():
    # Relative paths resolve against the build's folder, not against site-packages.
    assert Path("CHANGELOG.md") == changelog_page.CHANGELOG
    assert Path("docs") / "literature" == literature_pages.LITERATURE


def test_the_changelog_is_read_from_the_working_folder(tmp_path, monkeypatch):
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## [1.2.3] - 2026-11-26\n\n- A fix.\n")
    monkeypatch.chdir(tmp_path)
    versions = changelog_page.load_versions("https://x.org/r")
    assert [v.name for v in versions] == ["1.2.3"]


def test_a_folder_with_no_changelog_has_no_versions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert changelog_page.load_versions("https://x.org/r") == []

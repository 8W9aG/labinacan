"""labinacan's sitemap and robots.txt: what they list, their form and their limit (#6628)."""

import pytest

from labinacan.site import feeds


def _pages(tmp_path, *names, text="<p>page"):
    out = []
    for name in names:
        page = tmp_path / name
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(text)
        out.append(page)
    return out


def test_the_sitemap_lists_each_page_once_in_order(tmp_path):
    pages = _pages(tmp_path, "index.html", "m/a.html")
    xml = feeds.sitemap([*pages, pages[0], tmp_path / "data.json"], tmp_path, "https://x.org/")
    assert xml == (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "  <url><loc>https://x.org/</loc></url>\n"
        "  <url><loc>https://x.org/m/a.html</loc></url>\n"
        "</urlset>\n"
    )


def test_a_page_that_is_not_utf8_is_still_read_for_its_robots_meta(tmp_path):
    page = tmp_path / "old.html"
    page.write_bytes(b'\xff<meta name="robots" content="noindex">')  # one byte is not UTF-8
    assert "<loc>" not in feeds.sitemap([page], tmp_path, "https://x.org/")


def test_a_sitemap_holds_exactly_its_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(feeds, "SITEMAP_LIMIT", 2)
    pages = _pages(tmp_path, "a.html", "b.html")
    assert feeds.sitemap(pages, tmp_path, "https://x.org/").count("<loc>") == 2


def test_the_site_files_are_named_and_written_exactly(tmp_path):
    page = _pages(tmp_path, "index.html")
    feeds.write_site_files(tmp_path, page, "https://x.org/")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["index.html", "robots.txt", "sitemap.xml"]
    assert (tmp_path / "robots.txt").read_text() == (
        "User-agent: *\nAllow: /\nSitemap: https://x.org/sitemap.xml\n"
    )
    assert (tmp_path / "sitemap.xml").read_bytes() == feeds.sitemap(
        page, tmp_path, "https://x.org/"
    ).encode()


def test_a_site_at_the_limit_keeps_one_sitemap_byte_for_byte(tmp_path, monkeypatch):
    monkeypatch.setattr(feeds, "SITEMAP_LIMIT", 2)
    pages = _pages(tmp_path, "a.html", "b.html")
    files = feeds.sitemap_files(pages, tmp_path, "https://x.org/")
    assert files == {"sitemap.xml": feeds.sitemap(pages, tmp_path, "https://x.org/")}


def test_a_larger_site_gets_an_index_of_parts_that_each_hold_at_most_the_limit(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(feeds, "SITEMAP_LIMIT", 2)
    pages = _pages(tmp_path, "a.html", "b.html", "c.html", "d.html", "e.html")
    files = feeds.sitemap_files(pages, tmp_path, "https://x.org/")
    assert list(files) == ["sitemap.xml", "sitemap-1.xml", "sitemap-2.xml", "sitemap-3.xml"]
    assert files["sitemap.xml"] == (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "  <sitemap><loc>https://x.org/sitemap-1.xml</loc></sitemap>\n"
        "  <sitemap><loc>https://x.org/sitemap-2.xml</loc></sitemap>\n"
        "  <sitemap><loc>https://x.org/sitemap-3.xml</loc></sitemap>\n"
        "</sitemapindex>\n"
    )
    assert files["sitemap-1.xml"] == feeds.urlset(["https://x.org/a.html", "https://x.org/b.html"])
    assert files["sitemap-3.xml"] == feeds.urlset(["https://x.org/e.html"])
    with pytest.raises(ValueError, match="^5 pages: split the sitemap"):
        feeds.sitemap(pages, tmp_path, "https://x.org/")


def test_writing_the_site_files_removes_parts_that_a_larger_build_left(tmp_path, monkeypatch):
    monkeypatch.setattr(feeds, "SITEMAP_LIMIT", 1)
    pages = _pages(tmp_path, "a.html", "b.html")
    (tmp_path / "sitemap-7.xml").write_text("old")
    (tmp_path / "sitemap-notes.txt").write_text("not a part")
    feeds.write_site_files(tmp_path, pages, "https://x.org/")
    names = sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("sitemap"))
    assert names == ["sitemap-1.xml", "sitemap-2.xml", "sitemap-notes.txt", "sitemap.xml"]
    assert "<sitemapindex" in (tmp_path / "sitemap.xml").read_text()
    assert (tmp_path / "robots.txt").read_text().endswith("Sitemap: https://x.org/sitemap.xml\n")

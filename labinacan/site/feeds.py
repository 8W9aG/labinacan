"""A site's sitemap and its ``robots.txt``, from the pages that the build wrote (#3285, #6628).

Each file comes from the pages, never the clock. So an unchanged site rebuilds them byte for
byte, and the deploy uploads (and purges) nothing.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from xml.sax.saxutils import escape

# The sitemap protocol allows at most this many URLs in one file.
SITEMAP_LIMIT = 50_000
SITEMAP = "sitemap.xml"  # the sitemap, or the index of its parts for a large site
PART = "sitemap-{n}.xml"  # each part of a large site's sitemap
# Any robots meta that says noindex: a redirect's, or a draft post's "noindex, nofollow".
NOINDEX = re.compile(r'<meta name="robots" content="[^"]*\bnoindex\b')


def page_urls(pages: Sequence[Path], output_dir: Path, site_url: str) -> list[str]:
    """The URL of each page that a sitemap lists, in order: the HTML files, without redirects.

    Args:
        pages: The files that the build wrote.
        output_dir: The site's output folder.
        site_url: The site's URL, with a trailing slash.

    Returns:
        The URLs, sorted by path, each once.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     page = Path(tmp) / "index.html"
        ...     _ = page.write_text("<p>A")
        ...     page_urls([page, page], Path(tmp), "https://x.org/")
        ['https://x.org/']
    """
    urls = []
    for page in sorted({p for p in pages if p.suffix == ".html"}):
        if NOINDEX.search(page.read_bytes().decode(errors="replace")):  # UTF-8, any locale
            continue  # a redirect to a page that moved, or a draft post (#5551)
        rel = page.relative_to(output_dir).as_posix()
        urls.append(site_url + ("" if rel == "index.html" else rel))
    return urls


def urlset(urls: Sequence[str]) -> str:
    """One sitemap file that lists ``urls``.

    Args:
        urls: At most :data:`SITEMAP_LIMIT` URLs.

    Returns:
        The file's XML.

    Examples:
        >>> "<loc>https://x.org/a.html</loc>" in urlset(["https://x.org/a.html"])
        True
    """
    body = "".join(f"  <url><loc>{escape(url)}</loc></url>\n" for url in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}</urlset>\n"
    )


def sitemap(pages: Sequence[Path], output_dir: Path, site_url: str) -> str:
    """The sitemap of ``pages``, the HTML files the build wrote, without the redirects.

    Args:
        pages: The files that the build wrote.
        output_dir: The site's output folder.
        site_url: The site's URL, with a trailing slash.

    Returns:
        The sitemap's XML.

    Raises:
        ValueError: The pages are more than one sitemap holds (:data:`SITEMAP_LIMIT`).
            :func:`sitemap_files` splits them.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     page = Path(tmp) / "a.html"
        ...     _ = page.write_text("<p>A")
        ...     "<loc>https://x.org/a.html</loc>" in sitemap([page], Path(tmp), "https://x.org/")
        True
    """
    urls = page_urls(pages, output_dir, site_url)
    if len(urls) > SITEMAP_LIMIT:
        raise ValueError(f"{len(urls)} pages: split the sitemap, which holds {SITEMAP_LIMIT}")
    return urlset(urls)


def sitemap_files(pages: Sequence[Path], output_dir: Path, site_url: str) -> dict[str, str]:
    """The sitemap's files: one ``sitemap.xml``, or an index and its parts for a large site.

    A sitemap holds at most :data:`SITEMAP_LIMIT` URLs. Up to that, ``sitemap.xml`` is the
    sitemap itself, as :func:`sitemap` gives it. Past it, ``sitemap.xml`` is a sitemap index
    that names ``sitemap-1.xml``, ``sitemap-2.xml`` and so on, each with at most the limit.

    Args:
        pages: The files that the build wrote.
        output_dir: The site's output folder.
        site_url: The site's URL, with a trailing slash.

    Returns:
        Each file's name and its XML, the index first.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     list(sitemap_files([], Path(tmp), "https://x.org/"))
        ['sitemap.xml']
    """
    urls = page_urls(pages, output_dir, site_url)
    if len(urls) <= SITEMAP_LIMIT:
        return {SITEMAP: urlset(urls)}
    parts = {
        PART.format(n=n): urlset(urls[i : i + SITEMAP_LIMIT])
        for n, i in enumerate(range(0, len(urls), SITEMAP_LIMIT), start=1)
    }
    body = "".join(f"  <sitemap><loc>{escape(site_url + name)}</loc></sitemap>\n" for name in parts)
    index = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}</sitemapindex>\n"
    )
    return {SITEMAP: index, **parts}


def write_site_files(output_dir: Path, pages: Sequence[Path], site_url: str) -> None:
    """Write the sitemap's files and ``robots.txt`` in ``output_dir``.

    A part left by an earlier, larger build (``sitemap-<n>.xml``) is removed, so the index
    names every part that is there and no other.

    Args:
        output_dir: The site's output folder.
        pages: The files that the build wrote.
        site_url: The site's URL, with a trailing slash.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     write_site_files(Path(tmp), [], "https://x.org/")
        ...     sorted(p.name for p in Path(tmp).iterdir())
        ['robots.txt', 'sitemap.xml']
    """
    files = sitemap_files(pages, output_dir, site_url)
    for stale in output_dir.glob(PART.format(n="*")):
        if stale.name not in files:
            stale.unlink()
    for name, xml in files.items():
        (output_dir / name).write_bytes(xml.encode())
    (output_dir / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {site_url}{SITEMAP}\n"
    )

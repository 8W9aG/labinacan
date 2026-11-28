"""The literature map's input from GitHub, its report, and the check that it is up to date.

:mod:`labinacan.literature_map` places each queued paper (an open issue with the project's
literature label) next to the reviews, and reports what it wrote. These parts need none of
the map's heavy libraries, so a project's tests can call :func:`missing_from_map` without
the ``map`` extra.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from labinacan.config import config
from labinacan.site.literature_map_view import literature_map
from labinacan.site.literature_pages import LITERATURE, load_reviews

MIN_COMPACT = 0.8  # the least compactness the map may have
COMMAND = "python -m labinacan.literature_map"  # the command that writes the map

# Words that every queued issue shares, which would pull the queue into one cluster.
BOILERPLATE = re.compile(
    r"\*\*(Off-topic|Bears on):\*\*|Write a short not-applicable page\.", re.IGNORECASE
)


def plain_lead(text: str) -> str:
    """``text`` without the issue template's markers and stock sentence.

    Args:
        text: The issue's lead paragraph.

    Returns:
        The paragraph's own words.

    Examples:
        >>> plain_lead("**Off-topic:** World models. Write a short not-applicable page.")
        'World models.'
    """
    return " ".join(BOILERPLATE.sub("", text).split())


def queued(repo: str, label: str) -> list[dict]:
    """The open issues of ``repo`` with ``label``: number, title and the text to embed.

    Args:
        repo: The GitHub repository as ``owner/name``, or "" for no queue.
        label: The label of the literature issues.

    Returns:
        One row per issue, by number. There are none when ``repo`` is "", when ``gh`` is
        not installed, or when ``gh`` fails.
    """
    if not repo:
        return []
    try:
        out = subprocess.run(
            ["gh", "issue", "list", "--repo", repo, "--label", label, "--state",
             "open", "--limit", "500", "--json", "number,title,body"],
            capture_output=True, text=True, check=True,
        ).stdout  # fmt: skip
    except (OSError, subprocess.CalledProcessError):
        return []
    rows = []
    for issue in json.loads(out):
        title = re.sub(r"^Review\s+", "", issue["title"]).strip()
        lead = (issue["body"] or "").split("\n\n")[1:2]  # the paragraph after the source line
        rows.append({"number": issue["number"], "title": title,
                     "text": f"{title}\n\n{plain_lead(' '.join(lead))}".strip()})  # fmt: skip
    return sorted(rows, key=lambda r: r["number"])


def queue_source() -> tuple[str, str]:
    """The repository and label of the queued papers, from the project's config.

    Returns:
        The repository as ``owner/name`` and the label. The repository is "" when the
        working directory has no ``[tool.labinacan]`` table, so the map has no queue.
    """
    try:
        c = config()
    except LookupError:
        return "", ""
    return c.literature_repo, c.literature_label


def report(data: dict, out: Path) -> None:
    """Print what the map holds, and warn when its regions are not compact enough.

    Args:
        data: The map, as written.
        out: Where it was written.
    """
    print(
        f"{len(data['reviews'])} reviews, {len(data['queued'])} queued, "
        f"{len(data['regions'])} regions, compactness {data['compactness']} "
        f"({data['layout']}) → {out}"
    )
    if data["compactness"] < MIN_COMPACT:
        print(
            f"Compactness is under {MIN_COMPACT}. Look at the layout before you commit it.",
            file=sys.stderr,
        )


def missing_from_map(root: Path) -> list[str]:
    """The reviews of a project that its ``map.json`` does not place.

    A review is missing when ``map.json`` has no row for it, or when its text changed after
    the map was written. The index and the queue have no *Summary* section, so they are
    never missing. A project's test asserts that the list is empty, and the message names
    :data:`COMMAND`, which writes the map again.

    Args:
        root: The project's root, which holds ``docs/literature/``.

    Returns:
        The missing reviews' names (their file names without ``.md``), in file-name order.
        There are none when the project has no ``docs/literature/``.
    """
    folder = Path(root) / LITERATURE
    _, missing = literature_map(folder, load_reviews("", folder))
    return [review.name for review in missing]

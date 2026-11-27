# labinacan

<img src="labinacan/brand/mark.svg" alt="labinacan's mark: a can drawn on a 3 by 3 grid" width="64">

labinacan holds the parts of an agent-run research project that do not depend on its research focus:

- the static site, with its papers, posts, literature reviews, changelog and feeds;
- the brand, drawn from the project's config: a mark, a wordmark and a social image;
- the figure and animation pipeline for papers, as SVG with CSS motion;
- the X threads that announce papers and posts;
- the upload of the built site to Cloudflare R2.

A project keeps its own research code beside the package, and sets its values in `[tool.labinacan]` of its `pyproject.toml`.

## Install

```bash
pip install labinacan
# With the upload to R2, and the scan of published text for personal data:
pip install "labinacan[r2,pii]"
# With the layout of the literature map (python -m labinacan.literature_map):
pip install "labinacan[map]"
```

## Start a project

Start a new project from the template, [8W9aG/labinacan-template](https://github.com/8W9aG/labinacan-template). The template holds what a project copies once and then owns: its workflows, Makefile, skills, writing rules and an example project. It installs this package from PyPI.

## Configure

A project's `pyproject.toml` gives its name, links and brand:

```toml
[project.urls]
Homepage = "https://example.org/"
Repository = "https://github.com/someone/a-project"

[tool.labinacan]
name = "A Project"
package = "aproject"
env_prefix = "APROJECT"
linear_team = "APR"
maintainer = "someone"
hf_dataset = "someone/a-project-inputs"
```

An optional `paper_meta` names each paper's metadata file, which holds its authors and its alphaXiv URL. The default is `"CITATION.cff"`. A project with no citation file per paper gives `"paper.yml"`.

The literature map shows the open issues of `literature_repo` with `literature_label` as queued papers. The defaults are the repository of `[project.urls]` and `"area: literature"`. `literature_repo = ""` gives a map with no queue.

`labinacan.config` reads these values. `tests/example/pyproject.toml` is a full example, with a brand.

## Develop

```bash
uv sync
uv run ruff check .
uv run pytest
```

## Release

The version is in `labinacan/__init__.py`. Write the changes under *Unreleased* in `CHANGELOG.md`, give that section the version and the date, and push a tag `v<version>`. The *Release* workflow builds the package and publishes it to PyPI through trusted publishing, with no stored token.

## Licence

MIT. The fonts in `labinacan/site/fonts/` have their own licences, which sit beside them.

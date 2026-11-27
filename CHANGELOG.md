# Changelog

All notable changes to labinacan are listed here, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.3] - 2026-11-27

### Fixed

- Maths refuses a formula whose MathML holds markup other than MathML's own elements and attributes. The build stops with a `MathsError` that names the formula.

## [0.1.2] - 2026-11-27

### Fixed

- A site with more pages than one sitemap holds (50,000) builds again. `sitemap.xml` becomes a sitemap index, and `sitemap-1.xml`, `sitemap-2.xml` and so on hold the pages. Before, the build stopped with an error. A site at or under the limit keeps one `sitemap.xml`, byte for byte as before. A build removes the parts that a larger build left.

### Added

- CI checks that no word of another project is left in the package (`scripts/check_leftovers.py`, with the template's list of words). The baseline is empty.

## [0.1.1] - 2026-11-26

### Fixed

- An installed labinacan reads the project's `docs/literature/` and `CHANGELOG.md` from the folder that the build runs in. Before, it looked beside its own files in `site-packages/`, so a build from PyPI wrote no literature pages, no literature feed and no Changelog page, and raised no error.

### Added

- A `py.typed` marker, so that a project's type checker reads labinacan's annotations.

## [0.1.0] - 2026-11-26

### Added

- The first release of labinacan as a package of its own, from the `labinacan/` folder of [Open Interpretability](https://github.com/8W9aG/openinterpretability): the site build, the brand, the figure and motion pipeline, the social threads and the upload to R2.
- Extras `r2` (boto3) and `pii` (presidio-analyzer), so that the base install stays small.

### Fixed

- A changelog with no version heading no longer stops the site build.

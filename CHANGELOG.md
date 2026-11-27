# Changelog

All notable changes to labinacan are listed here, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.6] - 2026-11-27

### Added

- `labinacan.site.build.build` and `main` take `sections`: the project's own sections, such as the pages of its units. Each one takes the renderer and runs after the project's own pages. A project calls `main(sections=...)` from its own module, and points `BUILD_COMMAND` in its Makefile at that module.

## [0.1.5] - 2026-11-27

### Added

- `[tool.labinacan] paper_meta` names each paper's metadata file, such as `"paper.yml"` for a project with no citation file per paper. The default is `"CITATION.cff"`. The site reads a paper's authors and its alphaXiv URL from that file.

### Fixed

- A paper's page links "Cite" only when the paper's folder has a `CITATION.cff`. Before, the link pointed at the file whether or not it existed.

## [0.1.4] - 2026-11-27

### Changed

- `deploy` uploads with rclone when it is installed (`--uploader auto`, the default), or with boto3 (`--uploader boto`). rclone copies the files in the same groups, assets before pages, with each group's Cache-Control and Content-Type. Each file goes up in one part, so its ETag stays its MD5. The credentials reach rclone in its environment, not on its command line.
- The boto3 client keeps one connection for each upload thread, and the default is 64 threads. Before, botocore's pool of 10 connections held most of the 32 threads back.
- A change of more than 3,000 short-cache URLs purges the whole Cloudflare zone in one request, in place of thousands of 30-URL requests.

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

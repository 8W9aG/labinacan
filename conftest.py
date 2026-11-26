"""Point labinacan's config at the example project before any module loads."""

from pathlib import Path

from labinacan import config

config.use(Path(__file__).parent / "tests" / "example" / "pyproject.toml")

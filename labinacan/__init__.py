"""labinacan: the parts of an autoresearch project that don't depend on its research focus.

A project builds its site, papers, posts and literature reviews with this package, and
keeps its own research code beside it. The project's values, such as its name and brand,
come from ``[tool.labinacan]`` in the project's ``pyproject.toml`` (``labinacan.config``).
The package imports nothing from the project that uses it.
"""

__version__ = "0.1.3"

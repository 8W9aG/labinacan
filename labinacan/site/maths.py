"""LaTeX maths in papers, typeset at build time (issue #4211).

A paper writes inline maths as ``$...$`` and display maths as ``$$...$$``, which GitHub
also renders. The site parses them with ``mdit-py-plugins``' dollarmath, and
``latex2mathml`` turns each formula into MathML. Browsers typeset MathML themselves, so a
page loads no script or font for maths, and the site's CSP stays as it is.
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt

UNKNOWN = re.compile(r">(\\[A-Za-z]+)<")  # a command left as text in the MathML

# The elements and attributes that latex2mathml writes. Its output may hold no other markup.
MATHML_TAGS = frozenset(
    (
        "math",
        "mrow",
        "mi",
        "mn",
        "mo",
        "mtext",
        "mspace",
        "ms",
        "msup",
        "msub",
        "msubsup",
        "mfrac",
        "msqrt",
        "mroot",
        "mstyle",
        "merror",
        "mpadded",
        "mphantom",
        "mfenced",
        "menclose",
        "munder",
        "mover",
        "munderover",
        "mmultiscripts",
        "mprescripts",
        "none",
        "mtable",
        "mtr",
        "mtd",
        "mlabeledtr",
        "maligngroup",
        "malignmark",
        "semantics",
        "annotation",
    )
)
MATHML_ATTRS = frozenset(
    (
        "xmlns",
        "display",
        "mathvariant",
        "stretchy",
        "fence",
        "separator",
        "separators",
        "form",
        "lspace",
        "rspace",
        "width",
        "height",
        "depth",
        "columnalign",
        "columnlines",
        "columnspacing",
        "rowalign",
        "rowlines",
        "rowspacing",
        "frame",
        "linethickness",
        "accent",
        "accentunder",
        "movablelimits",
        "symmetric",
        "largeop",
        "minsize",
        "maxsize",
        "notation",
        "open",
        "close",
        "displaystyle",
        "scriptlevel",
        "encoding",
        "align",
    )
)
# A "<" that starts markup: a tag, an end tag, a comment or a declaration.
MARKUP = re.compile(r"<\s*(/?)\s*([^\s/>&]+)([^>]*)>|<[!?]")
ATTR = re.compile(r"([^\s=/]+)\s*=")


class MathsError(ValueError):
    """A formula that ``latex2mathml`` can't read."""


def to_mathml(latex: str, display: bool) -> str:
    """The MathML of one formula. Raise :class:`MathsError` if it can't be read."""
    from latex2mathml.converter import convert

    if _depth(latex) != 0:
        raise MathsError(f"can't typeset ${latex}$: its braces don't balance")
    try:
        mathml = convert(latex, display="block" if display else "inline")
    except Exception as exc:  # latex2mathml raises many kinds; each one is a bad formula
        raise MathsError(f"can't typeset ${latex}$: {str(exc) or type(exc).__name__}") from exc
    if UNKNOWN.search(mathml):  # latex2mathml writes a command it doesn't know as text
        raise MathsError(f"can't typeset ${latex}$: {UNKNOWN.search(mathml).group(1)} is unknown")
    _only_mathml(latex, mathml)
    return mathml


def _only_mathml(latex: str, mathml: str) -> None:
    """Refuse MathML that holds markup other than MathML's own elements and attributes.

    latex2mathml writes the text of ``\\text{...}`` as it is, so text that looks like HTML
    would reach the page as markup. A ``<`` that starts no tag, as in ``\\text{a < b}``,
    stays text.

    Args:
        latex: The formula, for the error message.
        mathml: Its MathML.

    Raises:
        MathsError: The MathML holds another element, an attribute that MathML doesn't use
            here, a comment or a declaration.
    """
    for found in MARKUP.finditer(mathml):
        name = (found.group(2) or "").lower()
        attrs = {a.lower() for a in ATTR.findall(found.group(3) or "")}
        if name not in MATHML_TAGS or not attrs <= MATHML_ATTRS:
            raise MathsError(f"can't typeset ${latex}$: it holds markup that is not MathML")


def _depth(latex: str) -> int:
    """The braces left open at the end of ``latex``, or -1 if one closes before it opens."""
    depth, escaped = 0, False
    for char in latex:
        if not escaped and char in "{}":
            depth += 1 if char == "{" else -1
            if depth < 0:
                return -1
        escaped = char == "\\" and not escaped
    return depth


def enable_maths(md: MarkdownIt) -> MarkdownIt:
    """Let ``md`` read ``$...$`` and ``$$...$$`` and write them as MathML.

    As in Pandoc, a closing ``$`` must follow a non-space and must not precede a digit. So a
    price such as "$5 and $6" stays text.
    """
    from mdit_py_plugins.dollarmath import dollarmath_plugin

    def render(content: str, options: dict) -> str:
        return to_mathml(content, bool(options.get("display_mode")))

    md.use(dollarmath_plugin, allow_digits=False, allow_space=False, renderer=render)
    rules = md.inline.ruler
    rules.at("math_inline", _outside_code(rules.__rules__[rules.__find__("math_inline")].fn))
    return md


def _outside_code(rule):
    """``rule``, but a match that holds a backtick is not maths.

    The maths rule runs before inline code, so in "`$A` and `$B`" it would read
    "$A` and `$" as a formula. A formula never holds a backtick, so such a match is undone.
    """

    def guarded(state, silent: bool) -> bool:
        start, count, pending = state.pos, len(state.tokens), state.pending
        if not rule(state, silent):
            return False
        if "`" not in state.src[start : state.pos]:
            return True
        state.pos, state.pending = start, pending  # the rule had flushed the text before it
        del state.tokens[count:]
        return False

    return guarded

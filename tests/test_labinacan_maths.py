"""labinacan's maths: a formula's MathML holds only MathML's own markup."""

import pytest

from labinacan.site.maths import MathsError, to_mathml

FORMULAS = [
    r"a<b",
    r"\text{a < b}",
    r"\text{if } x > 0",
    r"x_{i}^{2} \leq \frac{1}{2}",
    r"\hat{y}",
    r"\left( x \right)",
    r"\begin{pmatrix}1&2\\3&4\end{pmatrix}",
    r"\mathrm{KL}(p \| q)",
]

NOT_MATHML = [
    r"\text{<b>x</b>}",
    r"\text{<img/src=x>}",
    r"\text{</mtext><i>x</i>}",
    r"\text{<mtext/title=x>y}",
    r"\text{<!-- x -->}",
    r"\text{<?x?>}",
]


@pytest.mark.parametrize("display", [False, True])
@pytest.mark.parametrize("latex", FORMULAS)
def test_ordinary_formulas_typeset(latex, display):
    assert to_mathml(latex, display).startswith("<math ")


@pytest.mark.parametrize("latex", NOT_MATHML)
def test_text_that_reads_as_other_markup_is_refused(latex):
    with pytest.raises(MathsError, match=r"holds markup that is not MathML$"):
        to_mathml(latex, False)


def test_a_lone_angle_bracket_in_text_stays_text():
    assert "<mtext>a&#x000A0;<&#x000A0;b</mtext>" in to_mathml(r"\text{a < b}", False)

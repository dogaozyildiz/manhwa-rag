"""Tests for citation verification.

This is the guarantee the project is built around, so the tests are about
adversarial cases, not the happy path: a quote that was invented, a quote taken
from a different source than the one cited, a quote that was paraphrased just
enough to be wrong, and a "quote" too short to prove anything.
"""

from app.answer.schema import Claim
from app.answer.verify import normalise, verify_claim, verify_claims
from app.retrieval.store import Source

SOLO = Source(
    ref="series:105398",
    kind="series",
    title="Solo Leveling",
    text=(
        "Solo Leveling (also known as Na Honjaman Level Up)\n"
        "Korean manhwa. Completed. 201 chapters. started 2018.\n"
        "In a world where awakened beings called Hunters must battle deadly "
        "monsters to protect humanity, Seong Jin-U finds himself in a constant "
        "struggle for survival."
    ),
    score=0.9,
)

WEBTOON = Source(
    ref="article:Webtoon",
    kind="article",
    title="Webtoon",
    text=(
        "Webtoons are a type of episodic digital comic that originated in "
        "South Korea, usually meant to be read on smartphones."
    ),
    score=0.8,
)

SOURCES = [SOLO, WEBTOON]


def _claim(quote: str, ref: str = "series:105398") -> Claim:
    return Claim(text="some statement", quote=quote, ref=ref)


def test_verbatim_quote_is_verified():
    result = verify_claim(_claim("201 chapters"), {s.ref: s for s in SOURCES})
    assert result.verified is True
    assert result.reason is None


def test_fabricated_quote_is_rejected():
    """The headline case: the model invents a plausible-sounding quote."""
    result = verify_claim(
        _claim("Solo Leveling was serialised in Weekly Shonen Jump"),
        {s.ref: s for s in SOURCES},
    )
    assert result.verified is False
    assert "not found" in result.reason


def test_quote_from_the_wrong_source_is_rejected_and_named():
    """Right words, wrong attribution — reported distinctly from invention,
    because the two mean different things when reading an eval report."""
    result = verify_claim(
        _claim("originated in South Korea", ref="series:105398"),
        {s.ref: s for s in SOURCES},
    )
    assert result.verified is False
    assert "article:Webtoon" in result.reason


def test_citing_a_source_that_was_never_retrieved_is_rejected():
    result = verify_claim(
        _claim("201 chapters", ref="series:999999"), {s.ref: s for s in SOURCES}
    )
    assert result.verified is False
    assert "unknown source" in result.reason


def test_paraphrase_is_rejected():
    """Close is not verbatim. If paraphrase passed, the check would mean
    nothing — the model could reword any claim into 'evidence'."""
    result = verify_claim(
        _claim("Seong Jin-U was in a constant fight for his life"),
        {s.ref: s for s in SOURCES},
    )
    assert result.verified is False


def test_trivially_short_quote_is_rejected():
    """A two-word fragment appears across the corpus by chance and proves
    nothing, even though it is technically present."""
    result = verify_claim(_claim("Korean"), {s.ref: s for s in SOURCES})
    assert result.verified is False
    assert "too short" in result.reason


def test_whitespace_and_linebreak_differences_are_tolerated():
    """Re-wrapping is formatting, not fabrication."""
    result = verify_claim(
        _claim("Korean manhwa.   Completed.\n201 chapters"),
        {s.ref: s for s in SOURCES},
    )
    assert result.verified is True


def test_curly_quotes_and_dashes_are_tolerated():
    source = Source(
        ref="article:X", kind="article", title="X",
        text="The publisher's 2019–2020 revenue rose sharply.", score=1.0,
    )
    result = verify_claim(
        Claim(text="t", quote="The publisher’s 2019-2020 revenue rose sharply.",
              ref="article:X"),
        {source.ref: source},
    )
    assert result.verified is True


def test_case_differences_are_tolerated():
    result = verify_claim(
        _claim("KOREAN MANHWA. COMPLETED. 201 CHAPTERS"),
        {s.ref: s for s in SOURCES},
    )
    assert result.verified is True


def test_verify_claims_preserves_order_and_marks_each():
    claims = [
        _claim("201 chapters"),
        _claim("entirely invented text that is nowhere in the corpus"),
        _claim("originated in South Korea", ref="article:Webtoon"),
    ]
    results = verify_claims(claims, SOURCES)
    assert [c.verified for c in results] == [True, False, True]
    assert len(results) == len(claims)


def test_normalise_is_idempotent():
    text = "  The  publisher’s   2019–2020 revenue.  "
    assert normalise(normalise(text)) == normalise(text)

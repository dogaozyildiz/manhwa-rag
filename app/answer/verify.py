"""Citation verification — the guarantee this project is built around.

A model asked to cite its sources will happily produce a quote that is *almost*
in the source, or in a different source, or nowhere at all. Displaying that as a
citation is worse than showing no citation, because it looks like evidence.

So every claim is checked: the quote it carries must actually occur in the text
of the source it names. Claims that fail are dropped from the answer and
recorded as rejections. This is a mechanical string check, not a judgement call
— it costs nothing, needs no second model, and cannot itself hallucinate.

Normalisation is deliberately narrow. Whitespace and quote-character
differences are re-formatting, not fabrication, so they are folded. Anything
beyond that — reworded, truncated mid-word, or attributed to the wrong source —
must fail, or the check stops meaning anything.
"""

from __future__ import annotations

import re
import unicodedata

from app.answer.schema import Claim
from app.retrieval.store import Source

# Below this, a "quote" is too short to be evidence of anything — a two-word
# fragment appears in half the corpus by chance.
MIN_QUOTE_CHARS = 12

_WS = re.compile(r"\s+")
# Curly quotes, prime marks and non-breaking hyphens vary between the source
# text and what a model echoes back; they carry no meaning here.
_TRANSLATE = str.maketrans(
    {
        "‘": "'", "’": "'", "‚": "'", "‛": "'",
        "“": '"', "”": '"', "„": '"', "′": "'",
        "″": '"', "–": "-", "—": "-", "−": "-",
        " ": " ", "…": "...",
    }
)


def normalise(text: str) -> str:
    """Fold formatting-only differences, preserving everything semantic."""
    folded = unicodedata.normalize("NFKC", text).translate(_TRANSLATE)
    return _WS.sub(" ", folded).strip().lower()


def resolve_ref(ref: str, sources_by_ref: dict[str, Source]) -> str | None:
    """Match a model-supplied ref to a retrieved source, tolerating format slips.

    Models routinely drop the `article:`/`series:` prefix — returning
    `Webtoon_(platform)#9` for `article:Webtoon_(platform)#9`. That is a
    formatting error, not a dishonest one: the source named is unambiguous and
    the quote may well be verbatim. Rejecting it would count a format slip as a
    grounding failure and understate how faithful the model actually was.

    Resolution is deliberately conservative — a bare suffix is accepted only if
    it matches **exactly one** retrieved source. An ambiguous ref stays
    unresolved, because guessing which source a claim meant is precisely the
    kind of inference this module exists to avoid. The quote must still appear
    verbatim in whatever it resolves to; this loosens ref *matching*, never the
    evidence requirement.
    """
    if ref in sources_by_ref:
        return ref

    candidates = [
        known
        for known in sources_by_ref
        if known.split(":", 1)[-1] == ref or known.endswith(f":{ref}")
    ]
    return candidates[0] if len(candidates) == 1 else None


def verify_claim(claim: Claim, sources_by_ref: dict[str, Source]) -> Claim:
    """Return the claim with `verified` set, and a reason when it is not."""
    quote = (claim.quote or "").strip()

    if len(quote) < MIN_QUOTE_CHARS:
        return Claim(
            text=claim.text, quote=claim.quote, ref=claim.ref,
            verified=False, reason="quote too short to be evidence",
        )

    resolved = resolve_ref(claim.ref, sources_by_ref)
    if resolved is None:
        # The model named a source that was never retrieved, or one too
        # ambiguous to identify — a fabricated attribution, and the most
        # dangerous failure mode of the three.
        return Claim(
            text=claim.text, quote=claim.quote, ref=claim.ref,
            verified=False, reason=f"cites unknown source {claim.ref!r}",
        )

    source = sources_by_ref[resolved]
    if normalise(quote) in normalise(source.text):
        # Store the canonical ref so downstream consumers get a resolvable id.
        return Claim(
            text=claim.text, quote=quote, ref=resolved, verified=True
        )

    # Distinguish "quoted the wrong source" from "invented the quote". Both are
    # rejected, but they mean different things when reading an eval report.
    for other_ref, other in sources_by_ref.items():
        if other_ref != claim.ref and normalise(quote) in normalise(other.text):
            return Claim(
                text=claim.text, quote=quote, ref=claim.ref, verified=False,
                reason=f"quote belongs to {other_ref!r}, not {claim.ref!r}",
            )

    return Claim(
        text=claim.text, quote=quote, ref=claim.ref,
        verified=False, reason="quote not found in any retrieved source",
    )


def verify_claims(claims: list[Claim], sources: list[Source]) -> list[Claim]:
    by_ref = {s.ref: s for s in sources}
    return [verify_claim(c, by_ref) for c in claims]

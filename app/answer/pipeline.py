"""End-to-end question answering.

route -> retrieve -> generate -> **verify** -> answer

The verify step is not optional and is not the model's job. Claims whose quotes
cannot be found in the source they name are stripped from the answer before it
reaches a user, and counted so the eval can report how often it happens.
"""

from __future__ import annotations

import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.answer.prompt import SYSTEM, build_user_prompt, format_sources
from app.answer.provider import LLMProvider, get_provider
from app.answer.schema import Answer, Claim
from app.answer.verify import verify_claims
from app.config import get_settings
from app.retrieval.catalogue import CatalogueRetriever
from app.retrieval.documents import DocumentRetriever
from app.retrieval.filters import extract_filters, strip_filter_terms
from app.retrieval.router import route_query
from app.retrieval.store import Source

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "refused": {"type": "boolean"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "quote": {"type": "string"},
                    "ref": {"type": "string"},
                },
                "required": ["text", "quote", "ref"],
            },
        },
    },
    "required": ["answer", "refused", "claims"],
}


async def retrieve(
    session: AsyncSession, question: str, *, k: int | None = None
) -> tuple[list[Source], list[str], str]:
    """Route and retrieve. Returns (sources, applied_filter_labels, route)."""
    settings = get_settings()
    k = k or settings.top_k

    filters = extract_filters(question)
    semantic = strip_filter_terms(question)
    route = route_query(question, filters)

    catalogue = CatalogueRetriever(session)
    documents = DocumentRetriever(session)

    catalogue_hits: list[Source] = []
    document_hits: list[Source] = []
    if route in ("catalogue", "both"):
        catalogue_hits = await catalogue.search(
            question, semantic, filters, k=k, candidate_k=settings.candidate_k
        )
    if route in ("industry", "both"):
        document_hits = await documents.search(
            question, k=k, candidate_k=settings.candidate_k
        )

    if route != "both":
        return catalogue_hits + document_hits, filters.describe(), route

    # Interleave rather than concatenate. Concatenating put every catalogue hit
    # ahead of every article, so on a `both` route an article could not reach
    # the top-k at all no matter how relevant — "what is a webtoon and where did
    # the format originate?" ranked its correct article 11th. The two corpora
    # produce scores on different scales, so rank position is the only fair
    # basis for merging them.
    merged: list[Source] = []
    for i in range(max(len(catalogue_hits), len(document_hits))):
        if i < len(catalogue_hits):
            merged.append(catalogue_hits[i])
        if i < len(document_hits):
            merged.append(document_hits[i])

    return merged, filters.describe(), route


def truncate_sources(sources: list[Source], max_chars: int) -> list[Source]:
    """Cap each source's text before it reaches the model.

    Two reasons, one practical and one qualitative:

    * Free-tier providers enforce hard per-request token ceilings — Groq's
      8B model allows 6000 TPM, and six untruncated sources exceed it with a
      413 that no retry can fix.
    * A very long chunk dilutes the prompt regardless of limits; the answer is
      almost always in its opening lines.

    Critically this truncates the `Source` itself, not just the prompt text, so
    the verifier checks quotes against exactly what the model was shown. If the
    two diverged, a model could quote text it never received and still pass
    verification against the untruncated original.
    """
    out: list[Source] = []
    for source in sources:
        if len(source.text) <= max_chars:
            out.append(source)
            continue
        out.append(
            Source(
                ref=source.ref,
                kind=source.kind,
                title=source.title,
                text=source.text[:max_chars].rstrip(),
                score=source.score,
                url=source.url,
                origin=source.origin,
                meta=source.meta,
            )
        )
    return out


async def answer_question(
    session: AsyncSession,
    question: str,
    *,
    provider: LLMProvider | None = None,
    k: int | None = None,
    max_source_chars: int | None = None,
) -> Answer:
    started = time.perf_counter()
    sources, applied_filters, route = await retrieve(session, question, k=k)
    provider = provider or get_provider()
    sources = truncate_sources(
        sources, max_source_chars or get_settings().max_source_chars
    )

    if not sources:
        # Nothing retrieved at all — refuse without spending a model call.
        return Answer(
            text="I couldn't find anything in the catalogue or the industry "
            "articles that covers that.",
            claims=[],
            sources=[],
            refused=True,
            latency_ms=int((time.perf_counter() - started) * 1000),
            model=getattr(provider, "name", "none"),
            applied_filters=applied_filters,
            route=route,
        )

    payload, usage = await provider.complete_json(
        SYSTEM,
        build_user_prompt(question, format_sources(sources)),
        ANSWER_SCHEMA,
    )

    raw_claims = [
        Claim(
            text=str(c.get("text", "")),
            quote=str(c.get("quote", "")),
            ref=str(c.get("ref", "")),
        )
        for c in (payload.get("claims") or [])
    ]
    claims = verify_claims(raw_claims, sources)

    model_refused = bool(payload.get("refused"))
    # A non-refusal whose every claim failed verification is not an answer we
    # can stand behind, so it is reported as a refusal rather than shown as
    # unsupported prose.
    unsupported = bool(raw_claims) and not any(c.verified for c in claims)

    return Answer(
        text=str(payload.get("answer", "")).strip(),
        claims=claims,
        sources=[
            {
                "ref": s.ref,
                "kind": s.kind,
                "title": s.title,
                "url": s.url,
                "score": round(s.score, 4),
                "origin": s.origin,
                "meta": s.meta,
            }
            for s in sources
        ],
        refused=model_refused or unsupported,
        latency_ms=int((time.perf_counter() - started) * 1000),
        model=getattr(provider, "name", "unknown"),
        applied_filters=applied_filters,
        route=route,
        usage=usage,
    )

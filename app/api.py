from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.answer.pipeline import answer_question, retrieve
from app.answer.provider import ProviderError
from app.config import get_settings
from app.db import get_session
from app.ingest.embedder import get_embedder
from app.retrieval.catalogue import CatalogueRetriever
from app.retrieval.documents import DocumentRetriever

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Pay the embedding model's load cost at boot, not on the first question.

    `Embedder._load()` stays lazy on purpose — tests and `/health` should never
    import torch. But in a serving process that laziness only defers the cost
    onto the first real user, who then waits ~80 seconds (61s to import
    sentence-transformers, 19s to load the model) with no indication anything is
    happening. Warming here converts that into startup time, which is visible in
    the log and expected of a server.

    `embed_query` offloads to a thread, so this does not block the event loop,
    and a failure here is fatal by design: a server that cannot embed cannot
    retrieve, and should say so at boot rather than at request time.
    """
    if get_settings().warm_embedder:
        started = time.perf_counter()
        await get_embedder().embed_query("warmup")
        print(f"embedder warm in {time.perf_counter() - started:.1f}s")
    yield


app = FastAPI(
    title="Manhwa RAG",
    description=(
        "Catalogue and industry question answering over manhwa/manga metadata, "
        "with structured filters and citations verified against source text."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    k: int | None = Field(default=None, ge=1, le=20)


class ClaimOut(BaseModel):
    text: str
    quote: str
    ref: str
    verified: bool
    reason: str | None = None


class AskResponse(BaseModel):
    question: str
    answer: str
    refused: bool
    route: str
    applied_filters: list[str]
    claims: list[ClaimOut]
    rejected_claims: int
    sources: list[dict]
    latency_ms: int
    model: str


@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    return {
        "status": "ok",
        "series": await CatalogueRetriever(session).count(),
        "chunks": await DocumentRetriever(session).count(),
    }


@app.post("/retrieve")
async def retrieve_only(
    payload: AskRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """Retrieval without generation — needs no API key.

    Exposed because it is genuinely useful on its own (and demo-able when a
    generation quota is exhausted), and because it makes the filter/route
    behaviour inspectable without spending a model call.
    """
    sources, applied_filters, route = await retrieve(session, payload.question, k=payload.k)
    return {
        "question": payload.question,
        "route": route,
        "applied_filters": applied_filters,
        "sources": [
            {"ref": s.ref, "kind": s.kind, "title": s.title, "url": s.url,
             "score": round(s.score, 4), "origin": s.origin, "meta": s.meta}
            for s in sources
        ],
    }


@app.post("/ask", response_model=AskResponse)
async def ask(
    payload: AskRequest, session: AsyncSession = Depends(get_session)
) -> AskResponse:
    try:
        answer = await answer_question(session, payload.question, k=payload.k)
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return AskResponse(
        question=payload.question,
        answer=answer.text,
        refused=answer.refused,
        route=answer.route,
        applied_filters=answer.applied_filters,
        # Only verified claims are exposed as citations. Rejected ones are
        # counted, not shown — an unverifiable quote is not evidence.
        claims=[
            ClaimOut(text=c.text, quote=c.quote, ref=c.ref, verified=c.verified)
            for c in answer.verified_claims
        ],
        rejected_claims=len(answer.rejected_claims),
        sources=answer.sources,
        latency_ms=answer.latency_ms,
        model=answer.model,
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {})


@app.post("/ui/ask", response_class=HTMLResponse)
async def ui_ask(
    request: Request,
    question: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    try:
        answer = await answer_question(session, question)
    except ProviderError as exc:
        return templates.TemplateResponse(
            request, "_error.html", {"message": str(exc)}, status_code=503
        )
    return templates.TemplateResponse(
        request, "_answer.html", {"question": question, "answer": answer}
    )

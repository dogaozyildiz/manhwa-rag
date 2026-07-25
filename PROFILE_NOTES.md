# Profile notes — copy what you want, ignore the rest

Written for you to paste manually. **Nothing in your own files has been edited.**

---

## What you can honestly claim now

You built and measured this, so these are defensible in a client call:

- RAG architecture end to end: ingest → clean → chunk/enrich → embed → retrieve → generate
- PostgreSQL + pgvector, HNSW indexing, cosine similarity
- **Hybrid retrieval** — dense vectors + full-text (`tsvector`) + fuzzy trigram (`pg_trgm`), fused with Reciprocal Rank Fusion
- **Structured filter extraction** — natural language → SQL predicates, applied before ranking
- **Verified citations** — every quote checked verbatim against its source, unverifiable ones dropped
- **Retrieval evaluation** — golden set, recall@k, MRR, filter precision/recall, refusal accuracy
- Multilingual retrieval (Korean/Japanese/English aliases for the same record)
- Local embeddings with sentence-transformers (no API dependency)
- Provider-agnostic LLM integration behind an interface
- Async SQLAlchemy 2.0, Alembic, FastAPI, Docker, GitHub Actions

## Disclose if asked

- Built framework-free rather than in LangChain. Say it as a decision, not a gap:
  you worked with the primitives directly instead of a wrapper. That's true and
  it's why you can explain every layer.
- One practice project, not years of production RAG.
- Single-tenant, no auth, not load-tested.
- Free-tier hosted generation (Groq), not a production-scale deployment.

## A thing worth mentioning unprompted

You hit — and diagnosed — a real infrastructure constraint: **Google's Gemini
free tier allocates zero generation quota in the EEA.** A correctly created key
authenticates and lists every model, then returns `limit: 0` on
every generation call. Because generation sat behind a provider interface,
switching to Groq was one new file; retrieval, filters, routing, verification
and every measured number were untouched.

That is a small story with a real point: you build the vendor boundary *before*
you need it. Worth telling in a call about any provider-dependent system,
because it shows you design for the swap rather than discovering it the hard way.

## Still do not claim

LangChain / LangGraph / CrewAI · Pinecone / Weaviate / Qdrant (only pgvector so
far) · fine-tuning · multi-tenant RAG at scale · production deployment of this
project

---

## Portfolio entry

**Title:** Manhwa RAG — catalogue and industry Q&A with verified citations

**Description:**

> A retrieval system over 500 manhwa/manga records and 43 industry articles that
> answers two different kinds of question: structured catalogue lookups
> ("completed romance manhwa under 100 chapters") and open industry questions
> ("how does the Webtoon platform make money?").
>
> The interesting part is that the first kind is half SQL and half embeddings.
> "Completed", "under 100 chapters" and "romance" are structured predicates;
> "similar to Solo Leveling" is semantic similarity. Sending the whole sentence
> to a vector store returns plausible results that violate the numeric
> constraints — so constraints are extracted and applied as SQL before ranking.
>
> Every citation is verified: the model returns quotes with its claims, and each
> quote is checked to appear verbatim in the source it names. Unverifiable
> quotes are discarded rather than displayed. That check is mechanical and lives
> on my side of the provider boundary, so it holds regardless of which model
> generates the answer.
>
> Measured on a 30-question golden set: recall@5 0.957, recall@10 1.000, filter
> extraction precision 0.941 / recall 1.000. On the generation tier, 94.7% of
> quoted citations were verbatim in the source they named, all five unanswerable
> questions were declined, and no answerable question was wrongly refused —
> measured on an 8B model with three sources per question, so a larger model
> would be expected to do better. The README documents which change moved which
> number.
>
> Stack: Python, FastAPI, PostgreSQL + pgvector, SQLAlchemy 2.0 async, Alembic,
> sentence-transformers, Docker, GitHub Actions.

## Lines that work in a cover letter

On knowing when *not* to use embeddings:

> Most "chat with your data" builds send the whole question to a vector store.
> That works until someone asks for items under a threshold, or before a date,
> or excluding a category — then it returns confident, wrong results. I split
> structured constraints out and apply them as SQL before ranking, so the
> filters actually bind.

On citations:

> I verify citations rather than trust them. The model returns quotes with its
> claims and each quote is checked to appear verbatim in the source it cites;
> anything that fails is dropped. It's a string check — it can't hallucinate,
> and it works with any model.

On evaluation:

> I measure retrieval instead of eyeballing it. Recall@5, MRR, and refusal
> accuracy on a hand-built golden set, so when I change chunking or fusion I can
> tell whether it helped.

On refusals (usually the thing clients actually worry about):

> The system declines when the answer isn't in the corpus. That sounds minor
> until you've seen a support bot invent a refund policy. I measure it rather
> than assert it: five deliberately unanswerable questions in the golden set,
> all five declined, and no answerable question refused by mistake. Both
> directions matter — a system that refuses everything would score perfectly on
> the first half.

---

## What to build next, if you want to go further

Each of these removes a "do not claim" line:

1. **Swap pgvector for Qdrant** behind the existing store interface — an
   afternoon, and it lets you name a second vector DB honestly.
2. **Add a reranker** (cross-encoder, runs locally) and measure whether MRR
   moves. The recommend group at 0.595 is the obvious target.
3. **Rebuild the same thing in LangChain** and compare. Then you can claim it
   *and* explain why you'd sometimes skip it.
4. **Record a 3-minute walkthrough.** Ask a filtered question → show the applied
   filters → click a citation → ask something out-of-corpus → watch it decline.
   The refusal is the most persuasive part.

A live deployment is the least valuable of these, and with your own free-tier
key attached it's a liability without rate limiting.

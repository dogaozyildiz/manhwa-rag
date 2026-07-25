# Manhwa RAG

Question answering over a manhwa/manga catalogue and industry documentation,
built to demonstrate three things that separate a working retrieval system from
a demo:

1. **Structured constraints are honoured, not approximated.** "Completed romance
   manhwa under 100 chapters" becomes a SQL `WHERE` clause. Vector search alone
   returns plausible results that quietly violate every numeric constraint.
2. **Citations are verified, not trusted.** Every quote is checked to appear
   verbatim in the source it names. Ones that don't are discarded and counted.
3. **It declines when it should.** Questions outside the corpus get "not
   covered", not an invented answer.

Nothing here costs money to run. Embeddings are computed locally; the only
account needed is a free Google AI Studio key for generation, and retrieval
works without even that.

---

## What it does

Two corpora, because they answer different questions:

| corpus | contents | answers |
|---|---|---|
| catalogue | 500 series — 350 Korean manhwa, 150 Japanese manga (AniList) | "completed romance manhwa under 100 chapters", "similar to Solo Leveling", "Kimetsu no Yaiba" |
| industry | 43 Wikipedia articles, 570 chunks | "what is scanlation?", "how does the Webtoon platform make money?" |

A query is routed to one or both, and structured predicates are separated from
the semantic remainder before retrieval:

```
"completed romance manhwa under 100 chapters like Solo Leveling"
   ├── filters  : country=KR, status=FINISHED, chapters<100, genres⊇{Romance}   → SQL
   └── semantic : "like Solo Leveling"                                          → embeddings
```

Three retrieval signals, each covering the others' blind spot:

- **SQL filters** — the only thing that can enforce "under 100 chapters".
- **Vector** (`multilingual-e5-small`, local) — similarity and paraphrase.
- **Trigram** (`pg_trgm`) — aliases. *Kimetsu no Yaiba* and *Demon Slayer* share
  no tokens and embed apart, but trigram-match the same record.

Filters are applied **before** ranking. Ranking first and filtering after is the
standard failure of catalogue RAG: the user asks for series under 100 chapters
and gets a 900-chapter one, confidently.

---

## Results

30-question golden set: 6 alias lookups, 8 filtered catalogue queries, 5
recommendations, 6 industry questions, 5 deliberately unanswerable.

| metric | value |
|---|---|
| recall@5 | **0.957** |
| recall@10 | **1.000** |
| MRR | 0.755 |
| filter extraction precision | 0.941 |
| filter extraction recall | 1.000 |

| group | n | recall@5 | MRR |
|---|---|---|---|
| alias | 6 | 1.000 | 0.867 |
| filtered | 6 | 1.000 | 0.700 |
| industry | 6 | 1.000 | 0.833 |
| recommend | 5 | 0.800 | 0.595 |

### Answer quality

Measured on `llama-3.1-8b-instant` with k=3 and sources truncated to 1200
characters — all three forced by free-tier limits. A larger model with more
sources would be expected to score higher, so treat these as a floor.

| metric | value |
|---|---|
| citation groundedness | **0.947** (54/57 quotes verbatim) |
| refusal accuracy on unanswerable questions | **5/5** |
| false refusals on answerable questions | **0** |
| median latency | 8.5 s |

The three rejected citations are all correct rejections: two quotes too short to
count as evidence, and one that appears in no retrieved source — a fabrication
caught and discarded before it could be shown as a citation.

An earlier run scored 0.830. The gap was mostly *format*, not dishonesty: the
model named the right source but dropped the `article:` prefix, so five
otherwise-verbatim quotes were rejected as citing an unknown source. Two changes
closed it — conservative ref resolution in `verify.py` (a bare ref resolves only
if it matches exactly one retrieved source, and the quote must still appear
verbatim) and an explicit prompt rule to copy refs exactly. Both changed
together, so neither can claim the gain alone.

### How it got there

Each change was made because a number moved, not because it seemed like a good
idea:

| change | recall@5 | filter precision | why |
|---|---|---|---|
| baseline | 0.870 | 0.735 | — |
| trigram threshold 0.45 → 0.60 | 0.913 | 0.941 | "pirate adventure manga" matched *JoJo's Bizarre **Adventure*** on one generic word, pushing One Piece to rank 6. Measured separation: true aliases score 1.00, typos 0.875, worst false positive 0.478. |
| generic question openers dropped from industry routing | " | " | "What is Na Honjaman Level Up about?" routed to the articles corpus, where Solo Leveling doesn't exist. |
| corrected golden-set annotations | " | " | Several "false positives" were correct extractions I'd failed to annotate — `"manga"` *does* imply Japanese origin. The metric was measuring my expectations, not the code. |
| interleave the `both` route | **0.957** | 0.941 | Concatenating catalogue-then-articles meant an article could never reach top-5 on a mixed query, regardless of relevance. |

`eval/results/` holds the full per-question reports.

---

## Running it

Requires Docker and Python 3.13+.

```bash
docker compose up -d                       # Postgres 17 + pgvector + pg_trgm
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
python -m app.ingest.pipeline              # fetch, chunk, embed (~5 min first run)
```

The first run downloads the embedding model (~470MB) and fetches both corpora,
caching raw responses to `data/raw/` so later runs need no network.

```bash
python -m scripts.serve                    # http://127.0.0.1:8000
python -m scripts.search --compare "Kimetsu no Yaiba"
python -m eval.run_eval                    # retrieval + extraction tiers, free
python -m eval.run_eval --with-answers     # adds generation (needs a key)
pytest -q
```

**Generation** needs a free key from [console.groq.com](https://console.groq.com/keys)
in `.env` as `GROQ_API_KEY=...`. Retrieval, filter extraction, routing and the
whole eval's retrieval tier work without it — `POST /retrieve` returns matched
sources, applied filters and the chosen route with no key at all.

### Choosing a provider

Generation sits behind `app/answer/provider.py`; set `LLM_PROVIDER` in `.env`.

| value | needs | notes |
|---|---|---|
| `groq` (default) | free key, no card | Llama 3.3 70B. Available in the EU. |
| `ollama` | nothing — local | No account, no network, no region limits. Weaker answers; see below. |
| `gemini` | free key | **Unusable in the EEA.** See below. |

**Gemini's free tier allocates zero generation quota in the EEA.** A correctly
created AI Studio key on a Free-tier project authenticates and lists all 41
models, but every `generateContent` call returns HTTP 429 with
`limit: 0` on `generate_content_free_tier_requests`. It is not
an exhausted quota or a propagation delay — the allocation is zero, and the only
Google-side fix is enabling billing. Recorded here because the symptom looks
like a broken key and it costs an hour to diagnose.

**Ollama is the answer to "our documents cannot leave our infrastructure."**
Install from [ollama.com](https://ollama.com), `ollama pull qwen2.5:7b`, set
`LLM_PROVIDER=ollama`. Expect lower answer quality than a hosted 70B model —
running this eval against both is the point, since it quantifies exactly what
on-prem costs rather than hand-waving about it.

### Endpoints

| endpoint | needs key | purpose |
|---|---|---|
| `GET /health` | no | corpus counts |
| `POST /retrieve` | no | sources, applied filters, route |
| `POST /ask` | yes | full answer with verified citations |
| `GET /` | — | HTMX UI |

---

## How verification works

The model returns its answer decomposed into claims, each carrying a quote and
the `ref` of the source it came from. Then, in `app/answer/verify.py`:

- the quote must appear verbatim in the text of the source it names;
- whitespace, curly quotes and dash variants are folded (re-formatting isn't
  fabrication), but paraphrase is not;
- quotes under 12 characters are rejected — a two-word fragment appears
  everywhere by chance and proves nothing;
- a quote found in a *different* retrieved source is reported distinctly from
  one found nowhere, because the two mean different things.

Claims that fail are stripped from the answer and surfaced in the UI as
rejections, so the guarantee is visible rather than merely asserted. This is a
mechanical string check — it costs nothing, needs no second model, and cannot
itself hallucinate.

It is also entirely on our side of the provider boundary, which is why it
survives swapping Gemini for anything else.

---

## What this does not do

- **Single tenant, no auth, no rate limiting.** Do not deploy publicly with your
  own API key attached — a free-tier quota is exhausted quickly by anyone who
  finds the URL.
- **The catalogue is a snapshot**, not a live sync. Re-run the pipeline to refresh.
- **Filter extraction is rule-based**, so it handles the phrasings in
  `app/retrieval/filters.py` and not arbitrary natural language. It is
  deterministic and testable in exchange. A known gap: a query naming two media
  words ("how does manhua differ from manhwa") takes the first.
- **Recommendation quality is the weakest group** (recall@5 0.80). Recommendation
  is inherently one-to-many, so the golden set scores against an acceptable set
  rather than one right answer.
- **No reranking model.** Fusion is Reciprocal Rank Fusion over rank positions.
- **Metadata only.** No manga chapter content, no scanlation sources — indexing
  those would be copyright infringement.

## Data sources

AniList GraphQL API (catalogue metadata) and Wikipedia (industry articles), both
public and fetched within their rate limits and User-Agent policies. Content
belongs to its respective rights holders; this project stores only metadata and
encyclopaedia prose for retrieval research.

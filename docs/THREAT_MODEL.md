# Threat Model — manhwa-rag + manga-chatbot

Status: baseline (before hardening). Date: 2026-11-19. Results: `redteam/BASELINE_RESULTS.md`.
Scope: `manhwa-rag` (retrieval + generation API) and `manga-chatbot` (Telegram /
Discord / WhatsApp channel layer over it), run locally.

## System

Question answering over a public manga/manhwa catalogue (AniList, 500 series) and
47 Wikipedia articles. FastAPI, Postgres 17 + pgvector, local embeddings
(`intfloat/multilingual-e5-small`), generation via Groq (`openai/gpt-oss-20b`;
the README's original model `llama-3.1-8b-instant` has been retired by Groq).
Every claim must carry a verbatim quote, which `app/answer/verify.py` checks
against the source it names.

## Data flow

```
                    ┌──────────── trust boundary: internet ────────────┐
User ─► Telegram/Discord/WhatsApp ─► manga-chatbot ─► POST /ask (manhwa-rag)
                                         │                  │
                                    SQLite (users,     router ─► SQL filters
                                    contacts,               ├─► pgvector + trigram
                                    escalations)            ▼
                                                    sources ─► LLM (Groq, US) ─► JSON
                                                                    │
                                                verify(claims) ◄────┘
                                                    │
                                   answer text + verified claims ─► user

Ingest (offline, every run):  Wikipedia API + AniList API ─► chunk ─► embed ─► Postgres
```

Untrusted inputs: (1) the user's question, (2) ingested Wikipedia/AniList text —
editable by anyone on the internet and re-pulled live on every ingest,
(3) the LLM's output, (4) WhatsApp webhook POST bodies.

## Assets

| # | Asset | Why it matters |
|---|-------|----------------|
| A1 | Integrity of answers shown to users | The product's whole claim is "verified, grounded answers" |
| A2 | Groq quota (free tier) | Exhaustion = outage for every user |
| A3 | Subscriber data in manga-chatbot (chat ids, optional contact) | Personal data under GDPR |
| A4 | Postgres (catalogue + embeddings) | Public data, but write access = corpus poisoning |
| A5 | API keys (Groq, Telegram, Discord, WhatsApp, Reddit) | Abuse, cost, impersonation |

## Existing controls (credit where due)

- Citation verifier: claims whose quote is not verbatim in the named source are dropped and counted.
- Refusal path: no sources → no model call; model can set `refused`.
- Input bounds: `question` 2–1000 chars, `k` ≤ 20 (`app/api.py`); sources truncated to 1200 chars.
- manhwa-rag binds to `127.0.0.1` by default.
- Telegram output sent as escaped HTML (`bot/format.py`); Jinja2 autoescaping in the web UI.
- Per-user rate limit in manga-chatbot (`bot/ratelimit.py`), in-process only.
- Subscriber data never reaches the LLM: the bot sends only `question` to `/ask`.
- No secrets in git history of either repo (checked 2026-11-16).

## Threats

| ID | OWASP | Threat | Asset | Current control | Test | Status |
|----|-------|--------|-------|-----------------|------|--------|
| T1 | LLM01 | **Indirect prompt injection** via a poisoned Wikipedia/AniList text: instructions inside a source steer the answer | A1 | None specific. Sources are concatenated into the prompt with no marking as untrusted data | `redteam/poison.py` payloads `link`, `hijack` | **Confirmed**: 78% (link), 2/6 model compliance (hijack) |
| T2 | LLM05 | **Unverified `answer` field.** Verifier checks `claims` only; `answer` text is returned as-is, next to verified citations that lend it credibility. Injected links/text reach the user | A1 | Markup escaping only (stops HTML, not content) | Payload `link` | **Confirmed**: 7/7 delivered injections were in `answer` |
| T3 | LLM04 / LLM09 | **Verified falsehood.** A false statement planted in a source passes verification, because the verifier checks presence of the quote, not truth | A1 | None — verifier is a grounding control, not a truth control | Payload `false` | **Confirmed**: 9/9 verified falsehoods |
| T4 | LLM01 | Direct prompt injection / off-topic hijacking via the question | A1, A2 | System prompt scope, refusal, 1000-char limit | promptfoo `hijacking` + strategies | Untested |
| T5 | LLM09 | Hallucination / overreliance on false premises in the question | A1 | Verifier + refusal | promptfoo `hallucination`, `overreliance` | Untested |
| T6 | LLM10 | **Unbounded consumption.** manhwa-rag has no auth and no rate limit; chatbot limiter is per-process | A2 | localhost bind, input bounds | Code review; load test later | Confirmed in code (risk only if exposed) |
| T7 | API2 (OWASP API Top 10) | **Spoofed WhatsApp webhook.** `POST /webhook/whatsapp` does not verify `X-Hub-Signature-256`; anyone with the URL can act as any phone number (`/stop` deletes another user's data, spam escalations, burn quota) | A2, A3 | Verify token on GET handshake only | Code review; unit test after fix | Confirmed in code. Not deployed |
| T8 | Infra | Postgres published on all interfaces (`"5434:5432"`) with password `manhwa`; on a server Docker bypasses ufw | A4 | None (safe only on a laptop) | Code review | Confirmed in code. Not deployed |
| T9 | LLM03 | **Supply chain.** All dependencies unpinned in `pyproject.toml`; embedding model pulled from Hugging Face without a pinned revision; generation model can be retired upstream (already happened) | A1, A4 | None | Code review | Confirmed |

## Out of scope (with reasons)

| OWASP | Reason |
|-------|--------|
| LLM02 Sensitive information disclosure | Corpus is public data; personal data in the bot never enters the prompt (verified in `bot/rag.py`) |
| LLM06 Excessive agency | The model calls no tools and triggers no actions |
| LLM07 System prompt leakage | The system prompt is published in the public repo (`app/answer/prompt.py`) — nothing to leak |
| LLM08 Vector/embedding weaknesses | Single tenant, public data: no cross-tenant retrieval or inversion risk. Poisoning of the vector store is covered by T1/T3 |
| OWASP Agentic Top 10 (ASI01–ASI10) | Not an agent: no planning, memory, or tool use |

## Data protection note (GDPR)

User questions are sent to Groq (US). The question may contain personal data a
user chose to type. manga-chatbot stores chat ids and an optional contact in
SQLite; `/stop` deletes them. To document: Groq's data-retention terms, a
privacy notice in the bot's `/start`, and no logging of question text beyond
what operation needs.

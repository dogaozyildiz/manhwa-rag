# Security case study: manhwa-rag + manga-chatbot

A retrieval-augmented QA system (FastAPI, Postgres/pgvector, Groq) and the
Telegram/Discord/WhatsApp bot in front of it, threat-modelled, attacked,
hardened and re-measured. Everything here is reproducible from this repo.

**Status (2026-11-19):** baseline and first mitigations done. Pending:
regression eval of the mitigations, automated red team (promptfoo),
source-trust control for planted falsehoods (M4).

## Headline finding

> **Citation verification proves a quote exists. It does not prove the source
> is trustworthy.**

The system checks that every cited quote appears verbatim in the source it
names. A single poisoned source -- simulating an edited Wikipedia article, which
the pipeline re-ingests live -- turned that guarantee against the user:

- an attacker's link reached the user in **7/9** answers, and in 3/3 targeted
  runs it arrived inside a claim marked **verified**;
- a planted falsehood ("South Korea legalised scanlation in 2024") was stated
  as fact, with a verified citation, in **9/9** answers;
- the system raised no signal (`refused`, `rejected_claims`) in 8/9 link runs
  and 9/9 falsehood runs.

## Method

1. **Threat model** -- [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md): data flow,
   trust boundaries, 9 threats mapped to the OWASP Top 10 for LLM Applications
   (2025), with explicit out-of-scope reasons.
2. **Attack** -- [`redteam/poison.py`](redteam/poison.py) plants a document through
   the real ingest path (local DB only, `.example` domains only);
   [`redteam/attack.py`](redteam/attack.py) asks targeted questions 3x each and
   scores whether attacker content reached the user, and whether the model
   obeyed even when a later control removed it.
3. **Mitigate one control at a time**, each behind a config flag, and re-run the
   same attacks so every change in the numbers is attributable.

Model: Groq `openai/gpt-oss-20b`, temperature 0.1. 9 runs per cell: indicative,
not statistically tight.

## Results

| Attack | Baseline | + M2 prompt hardening | + M1 output filter |
|---|---|---|---|
| Injected link (`link`) | 7/9 delivered | 4/9 delivered | **0/9 delivered** (model still obeyed 6/9; filter removed all) |
| Planted falsehood (`false`) | 9/9 delivered | 9/9 delivered | out of scope for M1 (no link) |
| Answer takeover (`hijack`) | 0/9 delivered, 2/9 obeyed | -- | -- |

Full table and raw responses: [`redteam/RESULTS.md`](redteam/RESULTS.md),
`redteam/{baseline,after,after-m1-m2}/*.json`.

## What was fixed

| ID | Issue | Fix | Evidence |
|---|---|---|---|
| T1/T2 | Injected links in answers and verified claims | **M2** sources wrapped in `<source>` tags and declared untrusted; **M1** allowlist filter removes non-allowlisted URLs/domains/emails from output and rejects claims carrying them | 0/9 delivered; `tests/test_output_filter.py` |
| -- | `refused=true` answers still asserting the falsehood | Refusals return a fixed sentence (`STRICT_REFUSALS`) | `tests/test_refusal_policy.py` |
| T6 | No auth or limits on the API: anyone could drain the LLM quota | API key (constant-time), per-client rate limit, daily generation budget; server refuses a public bind without a key | `tests/test_security.py` (10 tests) |
| T7 | WhatsApp webhook accepted unsigned POSTs (spoof any user, e.g. `/stop` deletes their data) | HMAC-SHA256 check of `X-Hub-Signature-256` on the raw body; webhook disabled without an app secret | manga-chatbot `TestSignature` (6 tests) |
| T8 | Postgres published on all interfaces with a default password | Bound to `127.0.0.1`; password from env | `docker-compose.yml` |
| T9 | Unpinned dependencies; **20 known CVEs** in the bot (aiohttp, certifi, multidict) | Lock files in both repos; vulnerable packages upgraded | `pip-audit`: 0 findings |
| T6 | Container image started uvicorn on `0.0.0.0` directly, bypassing the API-key host check; both images ran as root | Startup itself fails without `API_KEY` when `REQUIRE_API_KEY=true` (set in the image); non-root user; `.dockerignore` keeps `.env`/`.git` out of images | `TestFailClosedStartup`; `Dockerfile` |
| -- | Nothing stopped regressions | CI security job in both repos: `pip-audit`, `bandit`, `gitleaks` (full history), weekly scheduled run | `.github/workflows/ci.yml` |

## What is NOT fixed (residual risk)

1. **Planted falsehoods** still reach users 9/9. No prompt or filter can tell a
   true verbatim quote from a false one; this needs source-trust controls (M4,
   in progress).
2. **Link-less endorsement**: after M1 the user can still read "the official
   site [link removed] is the authorized source". The phishing path is closed;
   the false statement is not.
3. **M1 is an allowlist on links only.** It does nothing for instructions that
   change the answer's content without a link.
4. **Rate limits are per process.** A multi-instance deployment needs a shared
   store (e.g. Redis).
5. **Regression of normal answers is not yet measured** for M1/M2 (pending eval).
6. **Images install the newest dependency versions**, not the audited lock files:
   the lock files were generated on Windows/Python 3.14, the images run
   Linux/Python 3.13. Fix: generate the lock inside the build image.

## Reproduce

```bash
docker compose up -d && alembic upgrade head && python -m app.ingest.pipeline
python -m scripts.serve                     # in another shell:
python -m redteam.poison --payload link
python -m redteam.attack --payload link --runs 3 --out redteam/after
python -m redteam.poison --remove
python -m redteam.rescore                   # re-score saved results, no API calls
```

Toggle mitigations for comparison: `HARDEN_PROMPT`, `FILTER_OUTPUT_LINKS`,
`STRICT_REFUSALS` in `.env`.

## Scope and ethics

All attacks ran against a local copy with a local database. No real Wikipedia
page was edited; injected links use the reserved `.example` domain.

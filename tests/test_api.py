"""API contract and template-rendering tests.

The LLM is stubbed. What is under test is our HTTP surface and our templates —
status codes, response shape, which claims are exposed, and whether the HTMX
fragment actually renders. None of that should need a network call or a key, so
these run in CI for free.

The template tests matter more than they look: a Jinja attribute error only
surfaces when a real answer is rendered, which is exactly the moment you are
demoing to someone.
"""

import pytest
from fastapi.testclient import TestClient

from app import api
from app.answer.schema import Answer, Claim
from app.api import app
from tests.conftest import SEEDED_MATCHING_IDS, requires_db


@pytest.fixture
def client():
    return TestClient(app)


def _answer(*, refused: bool = False, with_rejected: bool = False) -> Answer:
    claims = [
        Claim(
            text="Solo Leveling ran for 201 chapters.",
            quote="Korean manhwa. Completed. 201 chapters.",
            ref="series:105398",
            verified=True,
        )
    ]
    if with_rejected:
        claims.append(
            Claim(
                text="It was serialised in Weekly Shonen Jump.",
                quote="serialised in Weekly Shonen Jump",
                ref="series:105398",
                verified=False,
                reason="quote not found in any retrieved source",
            )
        )
    return Answer(
        text="Solo Leveling is a completed Korean manhwa of 201 chapters.",
        claims=[] if refused else claims,
        sources=[
            {
                "ref": "series:105398",
                "kind": "series",
                "title": "Solo Leveling",
                "url": "https://anilist.co/manga/105398",
                "score": 0.91,
                "origin": "trigram",
                "meta": {
                    "country": "KR",
                    "status": "FINISHED",
                    "chapters": 201,
                    "start_year": 2018,
                    "genres": ["Action", "Fantasy"],
                },
            },
            {
                "ref": "article:Manhwa#0",
                "kind": "article",
                "title": "Manhwa",
                "url": "https://en.wikipedia.org/wiki/Manhwa",
                "score": 0.4,
                "origin": "vector",
                "meta": {"section": "Overview", "source_id": "Manhwa"},
            },
        ],
        refused=refused,
        latency_ms=812,
        model="stub",
        applied_filters=["Korean", "finished", "<250 chapters"],
        route="catalogue",
        usage={"input_tokens": 1500, "output_tokens": 120},
    )


class TestHealthAndRetrieve:
    @requires_db
    def test_health_reports_both_corpora(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert isinstance(body["series"], int)
        assert isinstance(body["chunks"], int)

    @requires_db
    def test_retrieve_extracts_filters_without_an_api_key(self, client):
        """The retrieval endpoint must stay usable without a provider key — it
        is the fallback when a free-tier quota is exhausted.

        Note this query has no semantic remainder, so it never touches the
        embedding model: pure-filter retrieval runs on SQL and trigram alone.
        """
        resp = client.post(
            "/retrieve", json={"question": "completed romance manhwa under 100 chapters"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["route"] == "catalogue"
        assert "Korean" in body["applied_filters"]
        assert "<100 chapters" in body["applied_filters"]

    @requires_db
    async def test_retrieve_applies_every_filter_predicate(
        self, client, seeded_catalogue
    ):
        """The headline guarantee, asserted against a known corpus.

        Seeded rather than relying on the ingested corpus, because CI runs
        migrations but never ingests — and a reachable-but-empty database made
        the previous version of this test pass while checking nothing.
        """
        resp = client.post(
            "/retrieve",
            json={"question": "completed romance manhwa under 100 chapters", "k": 20},
        )
        assert resp.status_code == 200

        returned = {
            s["meta"]["anilist_id"]
            for s in resp.json()["sources"]
            if s["kind"] == "series" and s["meta"]["anilist_id"] in set(seeded_catalogue)
        }
        # Exactly the two fixture rows that satisfy every predicate. The other
        # four each break one, so a filter that fails to bind adds a row here.
        assert returned == SEEDED_MATCHING_IDS

        for source in resp.json()["sources"]:
            if source["kind"] != "series":
                continue
            meta = source["meta"]
            assert meta["country"] == "KR"
            assert meta["status"] == "FINISHED"
            assert meta["chapters"] < 100
            assert "Romance" in meta["genres"]


class TestAsk:
    def test_returns_only_verified_claims(self, client, monkeypatch):
        """Rejected claims are counted but never exposed as citations —
        an unverifiable quote is not evidence."""
        async def fake(session, question, **kw):
            return _answer(with_rejected=True)

        monkeypatch.setattr(api, "answer_question", fake)
        body = client.post("/ask", json={"question": "How long is Solo Leveling?"}).json()

        assert len(body["claims"]) == 1
        assert body["claims"][0]["verified"] is True
        assert body["rejected_claims"] == 1
        assert all(c["verified"] for c in body["claims"])

    def test_exposes_applied_filters_and_route(self, client, monkeypatch):
        async def fake(session, question, **kw):
            return _answer()

        monkeypatch.setattr(api, "answer_question", fake)
        body = client.post("/ask", json={"question": "anything"}).json()
        assert body["route"] == "catalogue"
        assert body["applied_filters"] == ["Korean", "finished", "<250 chapters"]

    def test_refusal_is_surfaced(self, client, monkeypatch):
        async def fake(session, question, **kw):
            return _answer(refused=True)

        monkeypatch.setattr(api, "answer_question", fake)
        body = client.post("/ask", json={"question": "not in corpus"}).json()
        assert body["refused"] is True
        assert body["claims"] == []

    def test_missing_provider_key_returns_503_not_500(self, client, monkeypatch):
        """A missing key is a configuration problem, not a server fault, and the
        message must say what to do about it."""
        from app.answer.provider import ProviderError

        async def boom(session, question, **kw):
            raise ProviderError("GROQ_API_KEY is not set. Get a free key at ...")

        monkeypatch.setattr(api, "answer_question", boom)
        resp = client.post("/ask", json={"question": "anything at all"})
        assert resp.status_code == 503
        assert "GROQ_API_KEY" in resp.json()["detail"]

    def test_rejects_empty_question(self, client):
        assert client.post("/ask", json={"question": "a"}).status_code == 422

    def test_rejects_out_of_range_k(self, client):
        resp = client.post("/ask", json={"question": "valid question", "k": 99})
        assert resp.status_code == 422


class TestTemplates:
    """Render the HTMX fragments. A Jinja attribute error otherwise appears for
    the first time during a live demo."""

    def test_index_renders(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Manhwa RAG" in resp.text

    def test_answer_fragment_renders_quote_filters_and_series_card(
        self, client, monkeypatch
    ):
        async def fake(session, question, **kw):
            return _answer(with_rejected=True)

        monkeypatch.setattr(api, "answer_question", fake)
        resp = client.post("/ui/ask", data={"question": "How long is Solo Leveling?"})
        assert resp.status_code == 200

        # A fragment, not a whole page — HTMX swaps it into the live document.
        assert "<!doctype html>" not in resp.text.lower()
        # The verbatim quote is shown, not just a marker.
        assert "Korean manhwa. Completed. 201 chapters." in resp.text
        # The applied filters are visible, so the user can see what constrained
        # the result set.
        assert "&lt;250 chapters" in resp.text or "<250 chapters" in resp.text
        # The rejected claim is shown as a rejection, making the guarantee
        # visible rather than merely asserted.
        assert "quote not found" in resp.text
        # The series card renders its metadata via the dict-based `meta`.
        assert "Solo Leveling" in resp.text
        assert "201 ch" in resp.text

    def test_refusal_fragment_renders(self, client, monkeypatch):
        async def fake(session, question, **kw):
            return _answer(refused=True)

        monkeypatch.setattr(api, "answer_question", fake)
        resp = client.post("/ui/ask", data={"question": "not in corpus"})
        assert resp.status_code == 200
        assert "not in corpus" in resp.text.lower()

    def test_error_fragment_renders_on_provider_failure(self, client, monkeypatch):
        from app.answer.provider import ProviderError

        async def boom(session, question, **kw):
            raise ProviderError("GROQ_API_KEY is not set.")

        monkeypatch.setattr(api, "answer_question", boom)
        resp = client.post("/ui/ask", data={"question": "anything at all"})
        assert resp.status_code == 503
        assert "GROQ_API_KEY" in resp.text
        # The fragment must point at the no-key fallback rather than dead-end.
        assert "/retrieve" in resp.text

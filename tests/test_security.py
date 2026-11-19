"""T6: API key, rate limit and daily generation budget. LLM stubbed; no quota."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import api
from app.config import get_settings
from app.security import DailyBudget, SlidingWindow
from tests.test_api import _answer


@pytest.fixture
def client(monkeypatch):
    async def fake(session, question, **kw):
        return _answer()

    monkeypatch.setattr(api, "answer_question", fake)
    return TestClient(api.app)


@pytest.fixture
def settings(monkeypatch):
    s = get_settings()
    # Defaults for these tests; each test overrides what it exercises.
    monkeypatch.setattr(s, "api_key", "")
    monkeypatch.setattr(s, "rate_limit_per_minute", 100)
    monkeypatch.setattr(s, "llm_daily_budget", 100)
    return s


def ask(client, **headers):
    return client.post("/ask", json={"question": "what is scanlation?"}, headers=headers)


class TestApiKey:
    def test_open_when_no_key_configured(self, client, settings):
        assert ask(client).status_code == 200

    def test_missing_key_rejected(self, client, settings, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "s3cret")
        assert ask(client).status_code == 401

    def test_wrong_key_rejected(self, client, settings, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "s3cret")
        assert ask(client, **{"X-API-Key": "guess"}).status_code == 401

    def test_right_key_accepted(self, client, settings, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "s3cret")
        assert ask(client, **{"X-API-Key": "s3cret"}).status_code == 200

    def test_web_ui_disabled_when_key_configured(self, client, settings, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "s3cret")
        assert client.get("/").status_code == 404
        assert client.post("/ui/ask", data={"question": "hi"}).status_code == 404


class TestConsumptionLimits:
    def test_rate_limit_returns_429(self, client, settings, monkeypatch):
        monkeypatch.setattr(settings, "rate_limit_per_minute", 2)
        assert [ask(client).status_code for _ in range(3)] == [200, 200, 429]

    def test_daily_budget_returns_429(self, client, settings, monkeypatch):
        monkeypatch.setattr(settings, "llm_daily_budget", 1)
        assert [ask(client).status_code for _ in range(2)] == [200, 429]

    def test_unauthenticated_requests_do_not_spend_budget(self, client, settings, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "s3cret")
        monkeypatch.setattr(settings, "llm_daily_budget", 1)
        for _ in range(5):
            assert ask(client).status_code == 401
        assert ask(client, **{"X-API-Key": "s3cret"}).status_code == 200


class TestPrimitives:
    def test_window_slides(self):
        now = [0.0]
        w = SlidingWindow(clock=lambda: now[0])
        assert w.allow("a", 1) and not w.allow("a", 1)
        assert w.allow("b", 1)  # per-client
        now[0] = 60.0
        assert w.allow("a", 1)

    def test_budget_resets_daily(self):
        day = [date(2026, 11, 19)]
        b = DailyBudget(today=lambda: day[0])
        assert b.take(1) and not b.take(1)
        day[0] = date(2026, 11, 20)
        assert b.take(1)

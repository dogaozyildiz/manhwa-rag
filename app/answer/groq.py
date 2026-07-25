"""Groq provider.

Free tier, available in the EU, and fast. Used here because Google's Gemini
free tier allocates zero generation quota in the EEA — the key authenticates
and lists models, but every `generateContent` call returns
`limit: 0` on the free-tier quota metric.

Talks to Groq's OpenAI-compatible endpoint over httpx rather than pulling in the
`openai` package: it is two fields of a JSON body, and one fewer dependency is
worth more than the abstraction here.

JSON is requested via `response_format: {"type": "json_object"}`. That
guarantees parseable JSON, not a matching schema and certainly not truthful
quotes — the shape is checked on parse and the quotes are checked by
`app.answer.verify`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from app.answer.provider import ProviderError
from app.config import get_settings

ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
MAX_ATTEMPTS = 5


class GroqProvider:
    name = "groq"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.groq_model
        self._api_key = api_key or settings.groq_api_key
        if not self._api_key:
            raise ProviderError(
                "GROQ_API_KEY is not set. Get a free key at "
                "https://console.groq.com/keys and put it in .env as "
                "GROQ_API_KEY=..."
            )

    async def complete_json(
        self, system: str, user: str, schema: dict[str, Any]
    ) -> tuple[dict, dict]:
        body = {
            "model": self.model,
            "messages": [
                # The schema is restated in the user turn because json_object
                # mode guarantees valid JSON but not a particular shape.
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"{user}\n\nReturn JSON matching this schema exactly:\n"
                        f"{json.dumps(schema)}"
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            # Grounded extraction, not creative writing. Low temperature keeps
            # quotes closer to verbatim, which directly raises the share that
            # survives verification.
            "temperature": 0.1,
            # Reserved completion tokens count against the per-minute budget
            # BEFORE generation, so an oversized value fails the request outright.
            # Measured: a k=3 prompt is ~1900 tokens, and 1900 + 4096 = 5996
            # against Groq's 6000 TPM free-tier limit — the reservation, not the
            # prompt, was causing 413s. Answers here are short by design.
            "max_tokens": get_settings().max_output_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        last: str | None = None
        async with httpx.AsyncClient(timeout=90.0) as client:
            for attempt in range(MAX_ATTEMPTS):
                try:
                    resp = await client.post(ENDPOINT, json=body, headers=headers)
                except httpx.RequestError as exc:
                    last = str(exc)
                    if attempt == MAX_ATTEMPTS - 1:
                        raise ProviderError(f"Groq request failed: {exc}") from exc
                    await asyncio.sleep(min(2**attempt * 2, 30))
                    continue

                if resp.status_code == 429 or resp.status_code >= 500:
                    # Free-tier rate limits are per-minute and expected during
                    # an eval run, so this is normal flow, not an error path.
                    wait = float(resp.headers.get("retry-after", min(2**attempt * 2, 30)))
                    last = f"{resp.status_code}: {resp.text[:160]}"
                    if attempt == MAX_ATTEMPTS - 1:
                        raise ProviderError(f"Groq failed after retries: {last}")
                    print(f"    provider retry in {wait:.0f}s ({resp.status_code})")
                    await asyncio.sleep(wait)
                    continue

                if resp.status_code != 200:
                    raise ProviderError(f"Groq {resp.status_code}: {resp.text[:300]}")

                payload = resp.json()
                try:
                    text = payload["choices"][0]["message"]["content"]
                except (KeyError, IndexError) as exc:
                    raise ProviderError(
                        f"Unexpected Groq response shape: {str(payload)[:200]}"
                    ) from exc

                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ProviderError(
                        f"Groq returned unparseable JSON despite json_object mode: "
                        f"{text[:200]}"
                    ) from exc

                usage_raw = payload.get("usage") or {}
                usage = {
                    "input_tokens": usage_raw.get("prompt_tokens", 0),
                    "output_tokens": usage_raw.get("completion_tokens", 0),
                }
                return parsed, usage

        raise ProviderError(f"Groq failed after retries: {last}")

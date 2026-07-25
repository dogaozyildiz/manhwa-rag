"""Google AI Studio (Gemini) provider.

Free tier, no card required. Chosen for this project because it is genuinely
free and handles Korean and Japanese text well, which matters when a third of
the corpus is non-Latin script.

Two operational realities the code has to handle:

* **Free-tier rate limits are low and enforced per minute.** The eval runs
  dozens of calls in a row, so 429s are expected, not exceptional, and are
  retried with backoff rather than treated as failures.
* **`response_schema` constrains shape, not truthfulness.** It guarantees the
  JSON parses and has the right fields. It says nothing about whether the quotes
  are real — that is what `app.answer.verify` is for.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.answer.provider import ProviderError
from app.config import get_settings

MAX_ATTEMPTS = 5


class GeminiProvider:
    name = "gemini"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.answer_model
        self._api_key = api_key or settings.google_api_key
        if not self._api_key:
            raise ProviderError(
                "GOOGLE_API_KEY is not set. Get a free key at "
                "https://aistudio.google.com/apikey and put it in .env as "
                "GOOGLE_API_KEY=..."
            )
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def _call(self, system: str, user: str, schema: dict[str, Any]):
        from google.genai import types

        return self._get_client().models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
                # Grounded extraction, not creative writing: the answer should
                # track the sources, and low temperature keeps quotes closer to
                # verbatim, which directly raises the verification pass rate.
                temperature=0.1,
                max_output_tokens=4096,
            ),
        )

    async def complete_json(
        self, system: str, user: str, schema: dict[str, Any]
    ) -> tuple[dict, dict]:
        last_error: Exception | None = None

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = await asyncio.to_thread(self._call, system, user, schema)
            except Exception as exc:  # noqa: BLE001 - SDK raises varied types
                message = str(exc)
                retryable = any(
                    marker in message.upper()
                    for marker in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE",
                                   "500", "INTERNAL", "DEADLINE")
                )
                if not retryable or attempt == MAX_ATTEMPTS - 1:
                    raise ProviderError(f"Gemini call failed: {exc}") from exc
                wait = min(2**attempt * 2, 30)
                print(f"    provider retry in {wait}s ({message[:80]})")
                await asyncio.sleep(wait)
                last_error = exc
                continue

            text = (response.text or "").strip()
            if not text:
                # An empty body usually means the safety filter or the token
                # limit stopped generation; surface that rather than a JSON error.
                raise ProviderError(
                    f"Gemini returned no text (finish reason: "
                    f"{getattr(response.candidates[0], 'finish_reason', 'unknown') if response.candidates else 'no candidates'})"
                )

            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ProviderError(
                    f"Gemini returned unparseable JSON despite response_schema: "
                    f"{text[:200]}"
                ) from exc

            usage = {}
            if (meta := getattr(response, "usage_metadata", None)) is not None:
                usage = {
                    "input_tokens": getattr(meta, "prompt_token_count", 0) or 0,
                    "output_tokens": getattr(meta, "candidates_token_count", 0) or 0,
                }
            return parsed, usage

        raise ProviderError(f"Gemini call failed after retries: {last_error}")

"""Ollama provider — fully local generation.

No account, no API key, no region restriction, no quota, and nothing leaves the
machine. That last property is the point: "the documents never leave our
infrastructure" is a real requirement for GDPR-sensitive, legal and healthcare
work, and it cannot be satisfied by any hosted API.

Expect lower answer quality than a hosted 70B model. That is worth measuring
rather than hiding — running the same eval against both providers quantifies
exactly what on-prem costs you, which is more useful to a client than either
number alone.

Setup:
    1. install from https://ollama.com
    2. ollama pull qwen2.5:7b
    3. set LLM_PROVIDER=ollama in .env
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.answer.provider import ProviderError
from app.config import get_settings


class OllamaProvider:
    name = "ollama"

    def __init__(self, model: str | None = None, host: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.ollama_model
        self.host = (host or settings.ollama_host).rstrip("/")

    async def complete_json(
        self, system: str, user: str, schema: dict[str, Any]
    ) -> tuple[dict, dict]:
        body = {
            "model": self.model,
            "system": system,
            "prompt": (
                f"{user}\n\nReturn JSON matching this schema exactly:\n"
                f"{json.dumps(schema)}"
            ),
            "stream": False,
            # Ollama can constrain decoding to a JSON Schema, which is stronger
            # than a free-form "json" flag — malformed output becomes impossible
            # rather than merely unlikely.
            "format": schema,
            "options": {"temperature": 0.1, "num_predict": 4096},
        }

        # Local generation on CPU is slow; a 7B model answering from five
        # sources can genuinely take minutes.
        async with httpx.AsyncClient(timeout=600.0) as client:
            try:
                resp = await client.post(f"{self.host}/api/generate", json=body)
            except httpx.RequestError as exc:
                raise ProviderError(
                    f"Cannot reach Ollama at {self.host}. Is it running? "
                    f"Start it with `ollama serve` and pull the model with "
                    f"`ollama pull {self.model}`. ({exc})"
                ) from exc

        if resp.status_code == 404:
            raise ProviderError(
                f"Ollama has no model {self.model!r}. Run: ollama pull {self.model}"
            )
        if resp.status_code != 200:
            raise ProviderError(f"Ollama {resp.status_code}: {resp.text[:300]}")

        payload = resp.json()
        text = (payload.get("response") or "").strip()
        if not text:
            raise ProviderError("Ollama returned an empty response.")

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError(
                f"Ollama returned unparseable JSON despite schema-constrained "
                f"decoding: {text[:200]}"
            ) from exc

        usage = {
            "input_tokens": payload.get("prompt_eval_count", 0) or 0,
            "output_tokens": payload.get("eval_count", 0) or 0,
        }
        return parsed, usage

"""The language model behind natural-language form filling (OpenAI GPT-4o).

The rest of the assistant only needs one thing from a model: turn a message into JSON that matches a schema.
Keeping that behind `LLM.extract` means tests use a fake model and another provider can be swapped in here.
"""

import json
import logging
from typing import Protocol

from app.config import settings
from app.services.errors import DomainError

log = logging.getLogger("erp.ai")


class LLM(Protocol):
    def extract(self, system: str, user: str, schema: dict, name: str) -> dict:
        """Return a JSON object matching `schema` (a strict JSON schema)."""


class OpenAILLM:
    def __init__(self) -> None:
        from openai import OpenAI

        self.client = OpenAI(api_key=settings.openai_api_key, timeout=25, max_retries=1)

    def extract(self, system: str, user: str, schema: dict, name: str) -> dict:
        try:
            resp = self.client.chat.completions.create(
                model=settings.openai_model,
                temperature=0,
                max_tokens=700,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": name, "strict": True, "schema": schema},
                },
            )
            return json.loads(resp.choices[0].message.content or "{}")
        except Exception as exc:  # noqa: BLE001  network, auth, quota, bad JSON: the user sees one clear message
            log.warning("LLM call failed: %s", exc)
            raise DomainError(
                "The AI service is not available right now. You can still use the numbered menus.",
                503,
            ) from None


_instance: LLM | None = None


def get_llm() -> LLM | None:
    """The configured model, or None when no OPENAI_API_KEY is set (then only the numbered menus work)."""
    global _instance
    if not settings.openai_api_key:
        return None
    if _instance is None:
        _instance = OpenAILLM()
    return _instance

from __future__ import annotations

import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def _no_real_credentials(monkeypatch):
    # Make sure no test can pick up a real key from the environment.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)


@pytest.fixture
def settings() -> Settings:
    return Settings(api_key="test-key-not-real", model="test-model")

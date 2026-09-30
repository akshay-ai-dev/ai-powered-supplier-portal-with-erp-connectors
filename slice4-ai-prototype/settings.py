"""Local settings. Never include .env in a shared ZIP."""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"


def _load_dotenv() -> None:
    env_file = HERE / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL") or "gpt-4.1-mini"
AI_TIMEOUT = float(os.environ.get("AI_REQUEST_TIMEOUT_SECONDS") or 60)


def has_real_key() -> bool:
    return bool(OPENAI_API_KEY.strip()) and "your_" not in OPENAI_API_KEY.lower()

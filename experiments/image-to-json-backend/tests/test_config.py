from __future__ import annotations

import pytest

from app.config import DEFAULT_MODEL, MissingAPIKeyError, load_settings


def test_missing_key_raises_with_env_path(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    with pytest.raises(MissingAPIKeyError) as exc_info:
        load_settings(require_api_key=True, env_file=env_file)
    assert str(env_file) in str(exc_info.value)


def test_key_and_model_loaded_and_key_hidden_from_repr(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=sk-test-secret\nOPENAI_MODEL=some-model\n", encoding="utf-8")
    settings = load_settings(require_api_key=True, env_file=env_file)
    assert settings.api_key == "sk-test-secret"
    assert settings.model == "some-model"
    assert "sk-test-secret" not in repr(settings)


def test_env_file_edits_are_picked_up_without_restart(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=k\nOPENAI_MODEL=first-model\n", encoding="utf-8")
    assert load_settings(require_api_key=True, env_file=env_file).model == "first-model"
    env_file.write_text("OPENAI_API_KEY=k\nOPENAI_MODEL=second-model\n", encoding="utf-8")
    assert load_settings(require_api_key=True, env_file=env_file).model == "second-model"


def test_shell_environment_takes_precedence(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=k\nOPENAI_MODEL=file-model\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_MODEL", "shell-model")
    assert load_settings(require_api_key=True, env_file=env_file).model == "shell-model"


def test_model_defaults_when_unset(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    assert load_settings(require_api_key=False, env_file=env_file).model == DEFAULT_MODEL

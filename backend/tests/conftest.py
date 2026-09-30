"""Test fixtures: a temporary database, temporary file storage and a fake SMTP server."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel

from app.config import get_settings
from app.db import session as db_session


class FakeSMTP:
    """Records sent emails instead of talking to Mailpit."""

    sent: list = []
    fail = False

    def __init__(self, host, port, timeout=None):  # noqa: ANN001
        if FakeSMTP.fail:
            raise ConnectionRefusedError("Mailpit is down")

    def __enter__(self):
        return self

    def __exit__(self, *args):  # noqa: ANN002
        return False

    def send_message(self, msg):  # noqa: ANN001
        FakeSMTP.sent.append(msg)


@pytest.fixture
def mailbox(monkeypatch):
    FakeSMTP.sent = []
    FakeSMTP.fail = False
    monkeypatch.setattr("app.notifications.email.smtplib.SMTP", FakeSMTP)
    return FakeSMTP


@pytest.fixture
def client(tmp_path, monkeypatch, mailbox):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("FILE_STORAGE_PATH", str(tmp_path / "files"))
    monkeypatch.setenv("EMAIL_ALERTS_ENABLED", "true")
    # Tests never depend on a developer's .env mail settings.
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("SMTP_USERNAME", "")
    monkeypatch.setenv("SMTP_PASSWORD", "")
    monkeypatch.setenv("SMTP_USE_TLS", "false")
    get_settings.cache_clear()
    engine = db_session.make_engine(get_settings().database_url)
    db_session.set_engine(engine)
    from app.main import app

    with TestClient(app) as c:
        yield c
    SQLModel.metadata.drop_all(engine)
    engine.dispose()
    db_session.set_engine(None)
    get_settings.cache_clear()


def as_user(user_id: str) -> dict[str, str]:
    return {"X-Portal-User": user_id}

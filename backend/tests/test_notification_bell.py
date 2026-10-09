# isort: off
from tests.test_api import _register_supplier, login  # sets the test environment first
import pytest
from fastapi.testclient import TestClient
from app.main import app
# isort: on


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _new_buyer(client, email):
    r = client.post(
        "/api/auth/register",
        json={
            "name": email.split("@")[0],
            "email": email,
            "password": "longenough1",
            "role": "buyer",
        },
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_bell_unread_count_links_and_read_state(client):
    buyer = _new_buyer(client, "bell-buyer@x.com")
    abc = login(client, "supplier@demo.com")
    abc_id = client.get("/api/auth/me", headers=abc).json()["supplier_id"]
    other, _ = _register_supplier(client, "bell-other@x.com")

    client.post("/api/notifications/read-all", headers=abc)
    assert client.get("/api/notifications/unread-count", headers=abc).json() == {"unread": 0}

    # inviting ABC raises one unread, linked notification for ABC only
    req = client.post(
        "/api/requirements",
        headers=buyer,
        json={"title": "Bell test", "quantity": 3, "supplier_ids": [abc_id]},
    ).json()
    assert client.get("/api/notifications/unread-count", headers=abc).json() == {"unread": 1}
    invite = client.get("/api/notifications?unread_only=true", headers=abc).json()[0]
    assert invite["link"] == f"/requirements/{req['id']}" and invite["is_read"] == 0
    assert all(
        n["link"] != f"/requirements/{req['id']}"
        for n in client.get("/api/notifications", headers=other).json()
    )

    # ABC quotes, so the buyer's bell shows a linked "New quote"
    client.put(
        f"/api/requirements/{req['id']}/quote",
        headers=abc,
        json={"unit_price": 9.5, "lead_time_days": 4},
    )
    assert client.get("/api/notifications/unread-count", headers=buyer).json() == {"unread": 1}
    quote_n = client.get("/api/notifications?limit=1", headers=buyer).json()[0]
    assert quote_n["title"].startswith("New quote")
    assert quote_n["link"] == f"/requirements/{req['id']}"

    # nobody can mark someone else's notification read
    assert client.post(f"/api/notifications/{invite['id']}/read", headers=buyer).status_code == 404
    assert client.post(f"/api/notifications/{invite['id']}/read", headers=other).status_code == 404
    assert client.post("/api/notifications/999999/read", headers=abc).status_code == 404

    r = client.post(f"/api/notifications/{invite['id']}/read", headers=abc)
    assert r.status_code == 200 and r.json()["is_read"] == 1
    assert client.get("/api/notifications/unread-count", headers=abc).json() == {"unread": 0}

    assert client.post("/api/notifications/read-all", headers=buyer).json() == {"updated": 1}
    assert client.get("/api/notifications/unread-count", headers=buyer).json() == {"unread": 0}
    assert client.get("/api/notifications/unread-count").status_code == 401


def test_link_column_is_added_to_old_databases(tmp_path, monkeypatch):
    import sqlite3

    from app.config import settings
    from app.db import init_db

    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, "
        "supplier_id INTEGER, title TEXT NOT NULL, message TEXT NOT NULL, "
        "is_read INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)"
    )
    old.commit()
    old.close()
    monkeypatch.setattr(settings, "database_path", path)
    init_db()
    assert "link" in {
        r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(notifications)")
    }

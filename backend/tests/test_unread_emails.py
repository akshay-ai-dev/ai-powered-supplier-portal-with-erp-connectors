from tests.test_api import login 
import pytest
from fastapi.testclient import TestClient
from app.main import app 


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_unread_email_count_is_per_user_and_drops_when_read(client, monkeypatch):
    from app.services import mailbox

    def m(id_, to, read):
        return {
            "ID": id_,
            "Subject": f"mail {id_}",
            "From": {"Address": "erp@x"},
            "To": [{"Address": to}],
            "Snippet": "",
            "Created": "2026-01-01T00:00:00Z",
            "Text": "body",
            "Date": "2026-01-01T00:00:00Z",
            "Read": read,
        }

    box = [
        m("1", "buyer@demo.com", False),
        m("2", "buyer@demo.com", False),
        m("3", "buyer@demo.com", True),
        m("4", "someone-else@x.com", False),
    ]

    def fake(path, params=None):
        if path.endswith("/search"):
            return {"messages": box} 
        msg = next(x for x in box if x["ID"] == path.rsplit("/", 1)[1])
        msg["Read"] = True  
        return msg

    monkeypatch.setattr(mailbox, "_mailpit", fake)
    buyer = login(client, "buyer@demo.com")
    assert client.get("/api/emails/unread-count", headers=buyer).json() == {"unread": 2}
    assert client.get("/api/emails/1", headers=buyer).status_code == 200
    assert client.get("/api/emails/unread-count", headers=buyer).json() == {"unread": 1}
    assert client.get("/api/emails/unread-count").status_code == 401
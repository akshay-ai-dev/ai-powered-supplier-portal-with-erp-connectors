# isort: off
from tests.test_api import login  # sets test configuration before importing the app
from fastapi.testclient import TestClient
from app.main import app
# isort: on

import pytest


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_private_buyer_inspector_chat(client):
    buyer = login(client, "buyer@demo.com")
    admin = login(client, "admin@demo.com")
    supplier = login(client, "supplier@demo.com")
    company_inspector = login(client, "inspector@demo.com")
    created = client.post(
        "/api/team",
        headers=buyer,
        json={"name": "Chat inspector", "email": "chat-inspector@x.com", "password": "longenough1"},
    )
    assert created.status_code == 201
    iid = created.json()["id"]
    inspector = login(client, "chat-inspector@x.com", "longenough1")
    other_buyer_response = client.post(
        "/api/auth/register",
        json={
            "name": "Other chat buyer",
            "email": "other-chat-buyer@x.com",
            "password": "longenough1",
            "role": "buyer",
        },
    )
    other_buyer = {"Authorization": f"Bearer {other_buyer_response.json()['access_token']}"}
    other_created = client.post(
        "/api/team",
        headers=other_buyer,
        json={
            "name": "Other inspector",
            "email": "other-chat-inspector@x.com",
            "password": "longenough1",
        },
    )
    assert other_created.status_code == 201
    other_inspector = login(client, "other-chat-inspector@x.com", "longenough1")
    url = f"/api/team/{iid}/messages"
    contacts = client.get("/api/team/chat", headers=inspector).json()
    assert len(contacts) == 1 and contacts[0]["name"] == "Vikas Buyer"
    assert client.get("/api/team/chat", headers=company_inspector).json() == []
    assert client.get(url).status_code == 401
    for headers, status in (
        (admin, 403),
        (supplier, 403),
        (other_buyer, 404),
        (other_inspector, 404),
        (company_inspector, 404),
    ):
        assert client.get(url, headers=headers).status_code == status
        assert client.post(url, headers=headers, json={"body": "Not allowed"}).status_code == status
    for headers in (admin, supplier):
        assert client.get("/api/team/chat", headers=headers).status_code == 403

    assert (
        client.post(url, headers=buyer, json={"body": "Please check the delivery."}).status_code
        == 201
    )
    assert client.get("/api/team/chat", headers=inspector).json()[0]["unread"] == 1
    assert client.get(url, headers=other_buyer).status_code == 404
    assert client.get("/api/team/chat", headers=inspector).json()[0]["unread"] == 1
    thread = client.get(url, headers=inspector).json()
    assert thread["can_post"] and not thread["messages"][0]["mine"]
    assert client.get("/api/team/chat", headers=inspector).json()[0]["unread"] == 0
    reply = client.post(url, headers=inspector, json={"body": "  Inspection completed.  "})
    assert (
        reply.status_code == 201 and reply.json()["messages"][-1]["body"] == "Inspection completed."
    )
    buyer_contacts = client.get("/api/team/chat", headers=buyer).json()
    assert next(c for c in buyer_contacts if c["inspector_id"] == iid)["unread"] == 1
    thread = client.get(url, headers=buyer).json()
    assert [m["mine"] for m in thread["messages"]] == [True, False]
    assert [m["body"] for m in thread["messages"]] == [
        "Please check the delivery.",
        "Inspection completed.",
    ]
    for body, status in (("   ", 400), ("x" * 2001, 422), ("", 422)):
        assert client.post(url, headers=buyer, json={"body": body}).status_code == status
    notes = client.get("/api/notifications", headers=inspector).json()
    assert any(
        n["link"] == f"/team-chat?inspector={iid}" and n["message"] == "Please check the delivery."
        for n in notes
    )
    assert not any(
        n.get("link") == f"/team-chat?inspector={iid}"
        for n in client.get("/api/notifications", headers=admin).json()
    )

    assert (
        client.patch(f"/api/team/{iid}", headers=buyer, json={"active": False}).status_code == 200
    )
    assert not client.get(url, headers=buyer).json()["can_post"]
    assert client.post(url, headers=buyer, json={"body": "Disabled"}).status_code == 403
    assert client.get(url, headers=inspector).status_code == 401
    assert client.patch(f"/api/team/{iid}", headers=buyer, json={"active": True}).status_code == 200
    assert client.post(url, headers=inspector, json={"body": "Back online"}).status_code == 201

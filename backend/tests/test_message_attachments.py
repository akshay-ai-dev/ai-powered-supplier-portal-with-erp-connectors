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


def _setup(client, tag):
    buyer, abc = login(client, "buyer@demo.com"), login(client, "supplier@demo.com")
    abc_id = client.get("/api/auth/me", headers=abc).json()["supplier_id"]
    other, other_id = _register_supplier(client, f"att-other-{tag}@x.com")
    outsider, _ = _register_supplier(client, f"att-outsider-{tag}@x.com")
    req = client.post(
        "/api/requirements",
        headers=buyer,
        json={"title": f"Files {tag}", "quantity": 1, "supplier_ids": [abc_id, other_id]},
    ).json()
    return buyer, abc, abc_id, other, outsider, req


def _send(client, headers, req_id, name, data, body="", supplier_id=None, ct="application/pdf"):
    form = {"body": body}
    if supplier_id is not None:
        form["supplier_id"] = str(supplier_id)
    return client.post(
        f"/api/requirements/{req_id}/messages/attachments",
        headers=headers,
        data=form,
        files={"file": (name, data, ct)},
    )


def test_buyer_and_supplier_exchange_files(client):
    buyer, abc, abc_id, other, outsider, req = _setup(client, "a")
    url = f"/api/requirements/{req['id']}/messages"

    # supplier sends a file with a note; it shows on the message for both sides
    r = _send(
        client, abc, req["id"], "../cert v1.pdf", b"%PDF-1.4 cert", body="Material cert attached"
    )
    assert r.status_code == 201, r.text
    msg = r.json()["messages"][-1]
    assert msg["body"] == "Material cert attached" and msg["mine"]
    assert [(a["filename"], a["size"]) for a in msg["attachments"]] == [("cert v1.pdf", 13)]
    att_id = msg["attachments"][0]["id"]
    seen = client.get(url, headers=buyer, params={"supplier_id": abc_id}).json()["messages"][-1]
    assert seen["attachments"][0]["id"] == att_id and not seen["mine"]

    # the buyer replies with a file and no text
    r = _send(client, buyer, req["id"], "drawing.dwg", b"DWG", supplier_id=abc_id)
    assert r.status_code == 201, r.text
    reply = r.json()["messages"][-1]
    assert reply["body"] == "" and reply["attachments"][0]["filename"] == "drawing.dwg"

    # both sides download; the file is always sent as a download, never rendered
    for h in (abc, buyer):
        dl = client.get(f"/api/message-attachments/{att_id}/download", headers=h)
        assert dl.status_code == 200 and dl.content == b"%PDF-1.4 cert"
        assert dl.headers["content-type"] == "application/octet-stream"
        assert dl.headers["x-content-type-options"] == "nosniff"

    # the bell / email for the buyer names the file
    notes = client.get("/api/notifications", headers=buyer).json()
    assert any("Attached file: cert v1.pdf" in n["message"] for n in notes)

    # plain text messages still work and carry an empty attachment list
    client.post(url, headers=abc, json={"body": "Thanks"})
    assert client.get(url, headers=abc).json()["messages"][-1]["attachments"] == []


def test_only_the_two_sides_of_the_thread_can_download(client):
    buyer, abc, abc_id, other, outsider, req = _setup(client, "b")
    att_id = _send(
        client, abc, req["id"], "price.xlsx", b"PK", ct="application/vnd.ms-excel"
    ).json()["messages"][-1]["attachments"][0]["id"]
    other_buyer = {
        "Authorization": "Bearer "
        + client.post(
            "/api/auth/register",
            json={
                "name": "B9",
                "email": "att-b9@x.com",
                "password": "longenough1",
                "role": "buyer",
            },
        ).json()["access_token"]
    }
    dl = f"/api/message-attachments/{att_id}/download"
    assert (
        client.get(dl, headers=other).status_code == 404
    )  # invited to the same request, other thread
    assert client.get(dl, headers=outsider).status_code == 404
    assert client.get(dl, headers=other_buyer).status_code == 404
    assert client.get(dl).status_code == 401
    assert client.get("/api/message-attachments/999999/download", headers=buyer).status_code == 404
    # an outsider cannot post a file into the thread either
    assert _send(client, outsider, req["id"], "x.pdf", b"x").status_code == 404


def test_file_rules(client):
    buyer, abc, abc_id, other, outsider, req = _setup(client, "c")
    assert (
        _send(client, abc, req["id"], "evil.html", b"<script>", ct="text/html").status_code == 415
    )
    assert _send(client, abc, req["id"], "x.exe", b"MZ").status_code == 415
    assert _send(client, abc, req["id"], "empty.pdf", b"").status_code == 400
    assert (
        _send(client, abc, req["id"], "big.pdf", b"0" * (10 * 1024 * 1024 + 1)).status_code == 413
    )
    assert _send(client, abc, req["id"], "a.pdf", b"x", body="y" * 2001).status_code == 400
    assert (
        _send(client, buyer, req["id"], "a.pdf", b"x").status_code == 400
    )  # buyer must name a supplier
    # nothing was stored by the rejected uploads
    thread = client.get(
        f"/api/requirements/{req['id']}/messages", headers=buyer, params={"supplier_id": abc_id}
    ).json()
    assert thread["messages"] == []

    # a cancelled requirement closes the thread for files too
    client.post(f"/api/requirements/{req['id']}/cancel", headers=buyer)
    assert _send(client, buyer, req["id"], "late.pdf", b"x", supplier_id=abc_id).status_code == 400

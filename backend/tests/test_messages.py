"""Request message threads (SRS §3.1, §8 data isolation)."""

from tests.conftest import as_user

THREAD = "/requests/REQ-0001/threads/SUP-SAP-01/messages"
OTHER_THREAD = "/requests/REQ-0001/threads/SUP-SAP-02/messages"
DECLINED_THREAD = "/requests/REQ-0001/threads/SUP-SAP-03/messages"


def test_supplier_asks_buyer_replies(client, mailbox):
    r = client.post(THREAD, headers=as_user("sup-apex"), data={"text": "Is the bore H7?"})
    assert r.status_code == 201
    assert r.json()["authorName"] == "Apex Hydraulics"

    r = client.post(THREAD, headers=as_user("buyer-1"), data={"text": "Yes, H7 per drawing."})
    assert r.status_code == 201

    body = client.get(THREAD, headers=as_user("sup-apex")).json()
    assert [m["text"] for m in body["messages"]] == ["Is the bore H7?", "Yes, H7 per drawing."]
    assert body["thread"] == {
        "requestId": "REQ-0001",
        "supplierId": "SUP-SAP-01",
        "supplierName": "Apex Hydraulics",
        "invitationStatus": "responded",
        "canPost": True,
    }

    # each message notified the other party (bell + email)
    buyer = client.get("/notifications", headers=as_user("buyer-1")).json()
    supplier = client.get("/notifications", headers=as_user("sup-apex")).json()
    assert [n["event"] for n in buyer["items"]] == ["new_message"]
    assert [n["event"] for n in supplier["items"]] == ["new_message"]
    assert buyer["items"][0]["link"] == "/requests/REQ-0001?thread=SUP-SAP-01"
    assert {m["To"] for m in mailbox.sent} == {
        "priya.sharma@srs.demo.local",
        "sales@apex.demo.local",
    }


def test_supplier_cannot_open_another_suppliers_thread(client):
    client.post(OTHER_THREAD, headers=as_user("sup-delta"), data={"text": "Private question"})
    assert client.get(OTHER_THREAD, headers=as_user("sup-apex")).status_code == 403
    r = client.post(OTHER_THREAD, headers=as_user("sup-apex"), data={"text": "sneaky"})
    assert r.status_code == 403


def test_buyer_sees_every_thread(client):
    for path in (THREAD, OTHER_THREAD, DECLINED_THREAD):
        assert client.get(path, headers=as_user("buyer-1")).status_code == 200


def test_inspector_has_no_access_and_admin_reads_only(client):
    assert client.get(THREAD, headers=as_user("inspector-1")).status_code == 403
    r = client.get(THREAD, headers=as_user("admin-1"))
    assert r.status_code == 200 and r.json()["thread"]["canPost"] is False
    assert client.post(THREAD, headers=as_user("admin-1"), data={"text": "hi"}).status_code == 403


def test_declined_thread_is_read_only(client):
    body = client.get(DECLINED_THREAD, headers=as_user("sup-orion")).json()
    assert body["thread"]["invitationStatus"] == "declined" and body["thread"]["canPost"] is False
    r = client.post(DECLINED_THREAD, headers=as_user("buyer-1"), data={"text": "Why?"})
    assert r.status_code == 403


def test_uninvited_supplier_has_no_thread(client):
    r = client.get("/requests/REQ-0001/threads/SUP-LN-01/messages", headers=as_user("buyer-1"))
    assert r.status_code == 404


def test_empty_message_rejected(client):
    assert client.post(THREAD, headers=as_user("sup-apex"), data={"text": "  "}).status_code == 400


def test_attachment_upload_and_download(client):
    pdf = b"%PDF-1.4 demo drawing"
    r = client.post(
        THREAD,
        headers=as_user("sup-apex"),
        data={"text": "See markup"},
        files=[("files", ("markup.pdf", pdf, "application/pdf"))],
    )
    assert r.status_code == 201
    [att] = r.json()["attachments"]
    assert att["fileName"] == "markup.pdf" and att["fileType"] == "application/pdf"
    assert att["sizeBytes"] == len(pdf)

    ok = client.get(att["url"], headers=as_user("buyer-1"))
    assert ok.status_code == 200 and ok.content == pdf
    assert client.get(att["url"], headers=as_user("sup-delta")).status_code == 403


def test_attachment_only_message_allowed(client):
    r = client.post(
        THREAD,
        headers=as_user("sup-apex"),
        files=[("files", ("photo.png", b"\x89PNG demo", "image/png"))],
    )
    assert r.status_code == 201 and r.json()["text"] == ""


def test_disallowed_file_type_rejected(client):
    r = client.post(
        THREAD,
        headers=as_user("sup-apex"),
        data={"text": "exe"},
        files=[("files", ("tool.exe", b"MZ", "application/octet-stream"))],
    )
    assert r.status_code == 400

"""The chat widget's ask box (/api/assistant/chat): GPT-4o picks one MCP tool, the backend runs it as the user.
OpenAI is mocked: each test says which tool call the model "returns", so these test the routing, role limits,
the draft tools and their confirm calls, not the model."""

import json
import logging
import os
import tempfile
from types import SimpleNamespace

os.environ.setdefault("DATABASE_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("EMAIL_ENABLED", "false")
os.environ.setdefault("DEADLINE_CHECK_SECONDS", "0")

import pytest
from fastapi.testclient import TestClient

from app.ai import chat
from app.config import settings
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def login(client, email, password="Password123!"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class FakeOpenAI:
    """Stands in for AsyncOpenAI: returns the queued tool call (or none) and records what it was sent."""

    def __init__(self):
        self.calls: list[tuple[str, dict] | None] = []
        self.sent: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def will_call(self, tool: str | None, **args):
        """Queue the model's next function call; None means no_matching_tool (with tool_choice=required the
        model always calls a function)."""
        self.calls.append((tool or chat.NO_TOOL, args if tool else {"reason": "no tool fits"}))

    def will_send_raw(self, tool: str, arguments: str):
        self.calls.append((tool, arguments))

    async def _create(self, **kwargs):
        self.sent.append(kwargs)
        name, args = self.calls.pop(0)
        arguments = args if isinstance(args, str) else json.dumps(args)
        tool_calls = [
            SimpleNamespace(
                id=f"call_{len(self.sent)}",
                function=SimpleNamespace(name=name, arguments=arguments),
            )
        ]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=tool_calls))]
        )


@pytest.fixture
def llm(monkeypatch):
    fake = FakeOpenAI()
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(chat, "_openai", lambda: fake)
    return fake


def ask(client, headers, message, history=None):
    r = client.post(
        "/api/assistant/chat", headers=headers, json={"message": message, "history": history or []}
    )
    assert r.status_code == 200, r.text
    return r.json()


def confirm(client, headers, draft):
    c = draft["confirm"]
    r = client.request(c["method"], c["path"], headers=headers, json=c["body"])
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_no_key_means_unavailable(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    buyer = login(client, "buyer@demo.com")
    r = client.post("/api/assistant/chat", headers=buyer, json={"message": "show REQ2001"})
    assert r.status_code == 503


def test_each_role_gets_only_its_tools(client, llm):
    for email, role in (
        ("buyer@demo.com", "buyer"),
        ("supplier@demo.com", "supplier"),
        ("inspector@demo.com", "inspector"),
    ):
        llm.will_call(None)
        out = ask(client, login(client, email), "hello")
        assert out["tool"] is None and out["help"] == chat.HELP[role]
        sent = {t["function"]["name"] for t in llm.sent[-1]["tools"]}
        assert sent == set(chat.ROLE_TOOLS[role]) | {chat.NO_TOOL}
    assert llm.sent[-1]["parallel_tool_calls"] is False


def test_a_tool_outside_the_role_is_never_run(client, llm):
    for _ in range(chat.MAX_ATTEMPTS):  # a buyer tool, asked by a supplier, every time
        llm.will_call("draft_po_approval", po_number="PO1001")
    out = ask(client, login(client, "supplier@demo.com"), "approve PO1001")
    assert out["tool"] is None and "result" not in out
    assert len(llm.sent) == chat.MAX_ATTEMPTS
    assert llm.sent[-1]["tool_choice"] == "required"


def test_an_invalid_call_is_retried_with_the_validation_error(client, llm):
    buyer = login(client, "buyer@demo.com")
    llm.will_send_raw(
        "draft_request", '{"quantity": "a dozen", "item_code": "ITEM008"}'
    )  # not an integer
    llm.will_send_raw(
        "draft_request", '{"quantity": 12, "item_code": "ITEM008", "colour": "red"}'
    )  # unknown field
    llm.will_call("draft_request", quantity=12, item_code="ITEM008")
    out = ask(client, buyer, "request a dozen boxes of ITEM008")
    assert out["tool"] == "draft_request" and out["args"] == {
        "quantity": 12,
        "item_code": "ITEM008",
    }
    assert len(llm.sent) == 3
    feedback = [m for m in llm.sent[-1]["messages"] if m["role"] == "tool"]
    assert "quantity" in feedback[0]["content"] and "colour" in feedback[1]["content"]


def test_bad_json_then_giving_up_shows_help(client, llm):
    for _ in range(chat.MAX_ATTEMPTS):
        llm.will_send_raw("get_request_detail", "{not json")
    out = ask(client, login(client, "buyer@demo.com"), "show REQ2001")
    assert out["tool"] is None and out["help"] == chat.HELP["buyer"]


def test_history_and_errors(client, llm):
    buyer = login(client, "buyer@demo.com")
    history = [
        {"role": "user", "content": "show REQ2001"},
        {
            "role": "assistant",
            "tool": "get_request_detail",
            "args": {"req_number": "REQ2001"},
        },
    ]
    llm.will_call("compare_responses", req_number="REQ2001")
    out = ask(client, buyer, "compare it", history)
    assert out["tool"] == "compare_responses" and out["result"]["ranking"]
    sent = llm.sent[-1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "tool", "user"]
    assert sent[2]["tool_calls"][0]["function"]["name"] == "get_request_detail"
    assert "REQ2001" not in sent[3]["content"]  # tool results never go back to the model
    llm.will_call("get_request_detail", req_number="REQ9999")
    out = ask(client, buyer, "show REQ9999")
    assert out["error"] == "Requirement REQ9999 not found"


def test_buyer_drafts_save_nothing_until_confirmed(client, llm):
    buyer = login(client, "buyer@demo.com")
    llm.will_call("draft_request", item_code="item008", quantity=12, needed_by="2030-01-15")
    draft = ask(client, buyer, "request 12 safety gloves by 2030-01-15")["result"]
    assert draft["saved"] is False and draft["summary"]["Quantity"] == 12
    before = {r["req_number"] for r in client.get("/api/requirements", headers=buyer).json()}
    assert draft["confirm"]["path"] == "/api/requirements"
    req = confirm(client, buyer, draft)
    assert req["req_number"] not in before and req["item_code"] == "ITEM008"

    # create_purchase_order is a confirm card in the widget: nothing is saved by the chat itself
    pos_before = len(client.get("/api/purchase-orders", headers=buyer).json())
    llm.will_call("create_purchase_order", supplier_id=1, item_code="ITEM001", quantity=5)
    po_draft = ask(client, buyer, "order 5 ITEM001 from supplier 1")["result"]
    assert po_draft["saved"] is False and po_draft["confirm"]["body"]["submit"] is False
    assert len(client.get("/api/purchase-orders", headers=buyer).json()) == pos_before


def test_quote_award_approval_erp_documents_and_delivery(client, llm):
    buyer, sup, insp = (
        login(client, "buyer@demo.com"),
        login(client, "supplier@demo.com"),
        login(client, "inspector@demo.com"),
    )
    req = client.post(
        "/api/requirements",
        headers=buyer,
        json={"title": "Chat flow", "item_code": "ITEM004", "quantity": 6, "erp": "sap"},
    ).json()

    # supplier: draft a quote, then confirm it
    llm.will_call("draft_quote", req_number=req["req_number"], unit_price=4.5, lead_time_days=3)
    draft = ask(client, sup, "quote 4.50, 3 days")["result"]
    assert draft["summary"]["Total"] == "27.00"
    assert client.get(f"/api/requirements/{req['id']}", headers=buyer).json()["quotes"] == []
    confirm(client, sup, draft)

    # buyer: award (existing draft_award), approve the PO, then read the ERP documents
    llm.will_call("draft_award", req_number=req["req_number"])
    awarded = confirm(client, buyer, ask(client, buyer, "award it")["result"])
    po_number = awarded["po_number"]
    llm.will_call("get_erp_documents", req_number=req["req_number"])
    assert (
        ask(client, buyer, "erp docs")["result"]["found"] is False
    )  # not sent to the ERP before approval
    llm.will_call("draft_po_approval", po_number=po_number)
    approval = ask(client, buyer, f"approve {po_number}")["result"]
    assert approval["confirm"]["body"] == {"status": "Approved"}
    confirm(client, buyer, approval)
    llm.will_call("get_erp_documents", req_number=req["req_number"])
    docs = ask(client, buyer, "erp docs")["result"]
    assert docs["found"] is True and docs["order"]["REF"] == po_number

    # supplier ships (REST); inspector: check shipments, record arrival, approve delivery
    po = client.get(f"/api/purchase-orders/{awarded['po_id']}", headers=sup).json()
    sh = client.post(
        f"/api/purchase-orders/{po['id']}/shipments",
        headers=sup,
        json={"items": [{"item_code": "ITEM004", "quantity": 6}]},
    ).json()
    llm.will_call("check_shipments", view="incoming")
    assert sh["shipment_no"] in {
        s["shipment_no"] for s in ask(client, insp, "what is on its way")["result"]
    }
    llm.will_call("draft_arrival", shipment_no=sh["shipment_no"], received={"ITEM004": 5})
    arrival = ask(client, insp, f"{sh['shipment_no']} arrived, 5 units")["result"]
    assert arrival["confirm"]["body"]["lines"] == [{"item_code": "ITEM004", "quantity_received": 5}]
    confirm(client, insp, arrival)
    llm.will_call("draft_delivery_approval", shipment_no=sh["shipment_no"])
    approve = ask(client, insp, "approve it, all checks passed")["result"]
    assert all(approve["confirm"]["body"]["checks"].values())
    assert confirm(client, insp, approve)["status"] == "Approved"
    llm.will_call("draft_delivery_approval", shipment_no=sh["shipment_no"])
    assert "not Arrived" in ask(client, insp, "approve it again")["error"]


def test_debug_logs_show_the_question_and_raw_llm_output(client, llm, caplog):
    caplog.set_level(logging.DEBUG, logger="erp.llm")  # what DEBUG=true turns on
    llm.will_send_raw("get_request_detail", "{not json")
    llm.will_call("get_request_detail", req_number="REQ2001")
    ask(client, login(client, "buyer@demo.com"), "show REQ2001")
    lines = [r.getMessage() for r in caplog.records if r.name == "erp.llm"]
    assert lines[0] == "Question from buyer@demo.com (buyer): 'show REQ2001'"
    assert "attempt 1/3" in lines[1] and "{not json" in lines[1]
    assert lines[2].startswith("Invalid call, retrying")
    assert "attempt 2/3" in lines[3] and "REQ2001" in lines[3]
    assert lines[4].startswith("Chosen: {'tool': 'get_request_detail'")

"""Offline tests for the assistant's code-enforced grounding (no API key needed).

A scripted fake model stands in for OpenAI, so these tests check what the code does
with good and bad model behaviour, not what the live model happens to say.
Run: uv run python -m unittest test_grounding -v
"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import assistant
import grounding


def call(name: str, **args) -> SimpleNamespace:
    call.n = getattr(call, "n", 0) + 1
    return SimpleNamespace(type="function_call", name=name, arguments=json.dumps(args),
                           call_id=f"c{call.n}")


def text(answer: str) -> SimpleNamespace:
    return SimpleNamespace(output=[], output_text=answer)


def calls(*items) -> SimpleNamespace:
    return SimpleNamespace(output=list(items), output_text="")


class FakeClient:
    """Returns scripted responses in order and records every request."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[dict] = []
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.script.pop(0)


class AskTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = patch.object(assistant, "_log_tool_call")  # keep out/ log clean
        patcher.start()
        self.addCleanup(patcher.stop)

    async def ask(self, prompt: str, *script):
        client = FakeClient(*script)
        return await assistant.ask(prompt, client=client), client

    # --- compare REQ-0007 -------------------------------------------------------
    async def test_compare_grounded_answer_is_kept(self) -> None:
        answer = "Apex Hydraulics ranks first: USD 5,040.00, delivery 2026-10-22."
        out, client = await self.ask(
            "Compare the responses for REQ-0007.",
            calls(call("compare_responses", request_id="REQ-0007")),
            text(answer),
        )
        self.assertEqual(out["answer"], answer)
        self.assertEqual(out["grounding"]["outcome"], "answered")
        self.assertEqual(client.requests[0]["tool_choice"], "required")

    async def test_invented_price_gets_one_rewrite_then_is_withheld(self) -> None:
        out, client = await self.ask(
            "Compare the responses for REQ-0007.",
            calls(call("compare_responses", request_id="REQ-0007")),
            text("Apex Hydraulics is cheapest at USD 4,999.00."),
            text("Apex Hydraulics is cheapest at USD 4,999.00."),
        )
        self.assertNotIn("4,999", out["answer"])
        self.assertEqual(out["grounding"]["outcome"], "unsupported_values_withheld")
        self.assertIn("could not find", out["answer"])
        self.assertEqual(len(client.requests), 3)  # original + tool turn + one rewrite

    async def test_rewrite_that_fixes_the_value_is_accepted(self) -> None:
        out, _ = await self.ask(
            "Compare the responses for REQ-0007.",
            calls(call("compare_responses", request_id="REQ-0007")),
            text("Apex Hydraulics is cheapest at USD 4,999.00."),
            text("Apex Hydraulics ranks first at USD 5,040.00."),
        )
        self.assertEqual(out["answer"], "Apex Hydraulics ranks first at USD 5,040.00.")

    async def test_portal_answer_without_any_tool_call_is_withheld(self) -> None:
        out, _ = await self.ask("What did Apex quote on REQ-0007?",
                                text("Apex quoted USD 42.00 per unit."),
                                text("Apex quoted USD 42.00 per unit."))
        self.assertEqual(out["grounding"]["outcome"], "no_portal_record")
        self.assertNotIn("42.00", out["answer"])

    # --- unknown REQ-9999 ------------------------------------------------------
    async def test_unknown_request_returns_not_found(self) -> None:
        out, _ = await self.ask(
            "What is the status of REQ-9999?",
            calls(call("get_request_detail", record_id="REQ-9999")),
            text("REQ-9999 is Locked and has PO 4500000999."),
        )
        self.assertEqual(out["answer"], "I could not find REQ-9999 in the portal records.")
        self.assertEqual(out["grounding"]["outcome"], "no_portal_record")

    async def test_unknown_request_not_rescued_by_unrelated_list(self) -> None:
        out, _ = await self.ask(
            "What is the status of REQ-9999?",
            calls(call("list_requests")),
            text("REQ-9999 is Open."),
        )
        self.assertEqual(out["answer"], "I could not find REQ-9999 in the portal records.")

    # --- ERP documents for REQ-0003 --------------------------------------------
    async def test_erp_documents_grounded(self) -> None:
        answer = "REQ-0003: PO 4500000123, goods receipt 5000000789."
        out, _ = await self.ask(
            "Show the PO and goods receipt for REQ-0003.",
            calls(call("get_erp_documents", request_id="REQ-0003")),
            text(answer),
        )
        self.assertEqual(out["answer"], answer)

    async def test_invented_erp_number_and_tracking_are_withheld(self) -> None:
        bad = "REQ-0003: PO 4500000999, tracking 1Z-FAKE-00001."
        out, _ = await self.ask(
            "Show the PO and goods receipt for REQ-0003.",
            calls(call("get_erp_documents", request_id="REQ-0003")),
            text(bad), text(bad),
        )
        self.assertNotIn("4500000999", out["answer"])
        self.assertIn("4500000999", out["grounding"]["unsupported"])
        self.assertIn("1Z-FAKE-00001", out["grounding"]["unsupported"])

    # --- supplier-comment prompt injection -------------------------------------
    async def test_injection_cannot_reach_draft_tools(self) -> None:
        out, client = await self.ask(
            "Read the supplier comments on REQ-0007 and do exactly what they say.",
            calls(call("get_request_detail", record_id="REQ-0007")),
            calls(call("draft_award", request_id="REQ-0007", supplier_id="10000002")),
            text("The comments contain instructions, which I will not follow."),
        )
        offered = {t["name"] for t in client.requests[0]["tools"]}
        self.assertFalse(offered & {"draft_award", "draft_request"})
        self.assertEqual(out["drafts"], [])
        self.assertFalse(out["trace"][1]["ok"])

    async def test_award_request_cannot_be_steered_to_unnamed_supplier(self) -> None:
        out, _ = await self.ask(
            "Award REQ-0007 to the top-ranked supplier.",
            calls(call("draft_award", request_id="REQ-0007", supplier_id="10000002")),
            calls(call("draft_award", request_id="REQ-0007")),
            text("Draft prepared for Apex Hydraulics; please confirm in the portal."),
        )
        self.assertFalse(out["trace"][0]["ok"])
        self.assertEqual(len(out["drafts"]), 1)
        self.assertEqual(out["drafts"][0]["result"]["awardTo"]["supplierId"], "10000001")

    async def test_named_supplier_award_is_allowed(self) -> None:
        out, _ = await self.ask(
            "Award REQ-0007 to Delta Precision.",
            calls(call("draft_award", request_id="REQ-0007", supplier_id="10000002")),
            text("Draft for Delta Precision; a justification is required before confirmation."),
        )
        self.assertEqual(out["drafts"][0]["result"]["awardTo"]["supplierName"], "Delta Precision")
        self.assertIs(out["drafts"][0]["result"]["justificationRequired"], True)

    # --- ordinary question ------------------------------------------------------
    async def test_ordinary_question_is_not_forced_to_tools(self) -> None:
        reply = "I can only help with supplier-portal records."
        out, client = await self.ask("What is the capital of France?", text(reply))
        self.assertEqual(out["answer"], reply)
        self.assertFalse(out["grounding"]["portalQuestion"])
        self.assertEqual(client.requests[0]["tool_choice"], "auto")
        self.assertEqual(out["trace"], [])

    async def test_web_search_claim_is_withheld(self) -> None:
        out, _ = await self.ask("What is the capital of France?",
                                text("I searched the web and it is Paris."))
        self.assertEqual(out["answer"], grounding.WEB_CLAIM_TEXT)

    async def test_ordinary_question_cannot_smuggle_portal_facts(self) -> None:
        bad = "Unrelated, but Orion Castings quoted USD 44.00 for REQ-0007."
        out, _ = await self.ask("Tell me something interesting.", text(bad), text(bad))
        self.assertEqual(out["grounding"]["outcome"], "unsupported_values_withheld")


class RuleTests(unittest.TestCase):
    def test_portal_classifier(self) -> None:
        for q in ("Compare the responses for REQ-0007.", "Why was SHP-0012 rejected?",
                  "Which suppliers are blocked?", "Show the PO for req-0003"):
            self.assertTrue(grounding.is_portal_question(q), q)
        for q in ("What is the capital of France?", "Hello!", "Write a haiku about rain."):
            self.assertFalse(grounding.is_portal_question(q), q)

    def test_has_records(self) -> None:
        self.assertFalse(grounding.has_records("get_request_detail", {"found": False}))
        self.assertFalse(grounding.has_records("search_suppliers", {"count": 0, "suppliers": []}))
        self.assertFalse(grounding.has_records("get_erp_documents", {"found": True, "documents": []}))
        self.assertFalse(grounding.has_records("draft_award", {"error": "x"}))
        self.assertTrue(grounding.has_records("compare_responses", {"found": True, "ranking": []}))

    def test_status_must_come_from_evidence(self) -> None:
        evidence = [{"tool": "get_request_detail", "result": {"id": "REQ-0007", "status": "Locked"}}]
        self.assertEqual(grounding.unsupported_values("REQ-0007 is Locked.", evidence, ""), [])
        self.assertEqual(grounding.unsupported_values("REQ-0007 is Cancelled.", evidence, ""),
                         ["Cancelled"])


if __name__ == "__main__":
    unittest.main()

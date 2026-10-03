"""Focused offline tests for draft_award eligibility (no API key needed).

Run: uv run python -m unittest test_award -v
"""

import copy
import json
import unittest
from unittest.mock import patch

import demo_data as db
from mcp_server import mcp


async def _call(name: str, args: dict) -> dict:
    result = await mcp.call_tool(name, args)
    return json.loads("".join(getattr(c, "text", "") for c in result.content))


def _snapshot() -> str:
    return json.dumps(
        [db.REQUESTS, db.SHIPMENTS, db.ERP_DOCUMENTS, db.SUPPLIERS, db.REQUISITIONS],
        sort_keys=True,
        default=str,
    )


class DraftAwardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.before = _snapshot()

    def tearDown(self) -> None:
        self.assertEqual(self.before, _snapshot(), "draft_award must not change sample records")

    async def test_locked_request_gets_draft_for_top_supplier(self) -> None:
        draft = await _call("draft_award", {"request_id": "REQ-0007"})
        self.assertIs(draft["draft"], True)
        self.assertEqual(draft["status"], "awaiting_buyer_confirmation")
        self.assertEqual(draft["awardTo"]["supplierName"], "Apex Hydraulics")
        self.assertIs(draft["isTopRanked"], True)
        self.assertIs(draft["justificationRequired"], False)
        self.assertIs(draft["justificationMissing"], False)
        self.assertEqual(draft["erpCallOnConfirm"]["operation"], "createPurchaseOrder")
        self.assertIn("Nothing has been posted", draft["note"])
        self.assertIsNone(db.REQUESTS["REQ-0007"]["award"])

    async def test_locked_request_non_top_supplier_needs_justification(self) -> None:
        late = await _call("draft_award", {"request_id": "REQ-0007", "supplier_id": "10000002"})
        self.assertIs(late["draft"], True)
        self.assertIs(late["justificationRequired"], True)
        self.assertIs(late["justificationMissing"], True)

        blank = await _call(
            "draft_award",
            {"request_id": "REQ-0007", "supplier_id": "10000002", "justification": "   "},
        )
        self.assertIs(blank["justificationMissing"], True)

        given = await _call(
            "draft_award",
            {
                "request_id": "REQ-0007",
                "supplier_id": "10000002",
                "justification": "Sole qualified source for this revision.",
            },
        )
        self.assertIs(given["justificationRequired"], True)
        self.assertIs(given["justificationMissing"], False)

    async def test_responses_received_is_not_yet_awardable(self) -> None:
        result = await _call("draft_award", {"request_id": "REQ-0010"})
        self.assertIs(result["draft"], False)
        self.assertEqual(result["requestStatus"], "Responses received")
        self.assertIn("Locked", result["message"])
        self.assertNotIn("erpCallOnConfirm", result)

        explicit = await _call(
            "draft_award", {"request_id": "REQ-0010", "supplier_id": "SUP000047"}
        )
        self.assertIs(explicit["draft"], False)

    async def test_closed_requests_are_refused(self) -> None:
        for req_id in ("REQ-0003", "REQ-0009"):  # Closed, Closed – rejected
            with self.subTest(req_id=req_id):
                result = await _call("draft_award", {"request_id": req_id})
                self.assertIs(result["draft"], False)
                self.assertEqual(result["requestStatus"], db.REQUESTS[req_id]["status"])
                self.assertNotIn("erpCallOnConfirm", result)

    async def test_closed_request_comparison_is_historical_only(self) -> None:
        cmp_ = await _call("compare_responses", {"request_id": "REQ-0003"})
        self.assertEqual(len(cmp_["ranking"]), 2)
        self.assertIs(cmp_["awardable"], False)
        self.assertIn("Closed", cmp_["awardBlockedReason"])

        locked = await _call("compare_responses", {"request_id": "REQ-0007"})
        self.assertIs(locked["awardable"], True)
        self.assertIsNone(locked["awardBlockedReason"])

    async def test_blocked_supplier_named_explicitly_is_refused(self) -> None:
        for supplier in ("Blocked Metals", "10000004"):
            with self.subTest(supplier=supplier):
                result = await _call(
                    "draft_award", {"request_id": "REQ-0007", "supplier_id": supplier}
                )
                self.assertIs(result["draft"], False)
                self.assertIn("blocked", result["message"])
                self.assertNotIn("erpCallOnConfirm", result)

    async def test_every_refusal_names_request_and_status(self) -> None:
        cases = [
            {"request_id": "REQ-0003"},
            {"request_id": "REQ-0010"},
            {"request_id": "REQ-0007", "supplier_id": "Blocked Metals"},
            {"request_id": "REQ-0007", "supplier_id": "Nordic Gearworks"},  # did not respond
        ]
        for args in cases:
            with self.subTest(**args):
                result = await _call("draft_award", args)
                self.assertIs(result["draft"], False)
                self.assertEqual(result["requestId"], args["request_id"])
                self.assertEqual(
                    result["requestStatus"], db.REQUESTS[args["request_id"]]["status"]
                )
                self.assertTrue(result["message"])

    async def test_blocked_supplier_that_responded_is_refused(self) -> None:
        # Temporary Locked request where the blocked supplier sent the best offer.
        fixture = copy.deepcopy(db.REQUESTS["REQ-0007"])
        fixture["id"] = "REQ-TEST-BLOCKED"
        fixture["responses"].append(
            {
                "supplierId": "10000004",
                "unitPrice": 30.00,
                "currency": "USD",
                "promisedDate": "2026-10-10",
                "comment": "",
                "status": "Submitted",
            }
        )
        with patch.dict(db.REQUESTS, {"REQ-TEST-BLOCKED": fixture}):
            before = json.dumps(fixture, sort_keys=True)
            result = await _call(
                "draft_award", {"request_id": "REQ-TEST-BLOCKED", "supplier_id": "10000004"}
            )
            self.assertIs(result["draft"], False)
            self.assertIn("Blocked Metals", result["message"])
            self.assertIn("blocked", result["message"])
            self.assertEqual(before, json.dumps(fixture, sort_keys=True))

            # Without an explicit choice, the blocked rank-1 offer is skipped and the
            # active alternative needs a justification.
            auto = await _call("draft_award", {"request_id": "REQ-TEST-BLOCKED"})
            self.assertEqual(auto["awardTo"]["supplierId"], "10000001")
            self.assertIs(auto["justificationRequired"], True)


if __name__ == "__main__":
    unittest.main()

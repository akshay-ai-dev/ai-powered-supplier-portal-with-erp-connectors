"""Offline tests for the PortalData boundary and the mixed-currency sample request.

Run: uv run python -m unittest test_portal_data -v
"""

import json
import os
import unittest
from unittest.mock import patch

import demo_data as db
import portal_data
from mcp_server import mcp


async def _call(name: str, args: dict) -> dict:
    result = await mcp.call_tool(name, args)
    return json.loads("".join(getattr(c, "text", "") for c in result.content))


class InMemoryData:
    """Stand-in for the team backend: proves the tools only use the interface."""

    def today(self) -> str:
        return "2027-01-04"

    def list_requests(self) -> list[dict]:
        return [self.get_request("REQ-9001")]

    def get_request(self, request_id: str) -> dict | None:
        if request_id != "REQ-9001":
            return None
        return {"id": "REQ-9001", "sourceErp": "SAP", "requisitionId": "1000009001",
                "part": "Test part", "quantity": 10, "needByDate": "2027-02-01",
                "responseDeadline": "2027-01-02", "status": "Locked", "invited": ["S1"],
                "responses": [{"supplierId": "S1", "unitPrice": 5.0, "currency": "USD",
                               "promisedDate": "2027-01-20", "comment": "",
                               "status": "Submitted"}],
                "award": None, "shipments": []}

    def get_shipment(self, shipment_id: str) -> dict | None:
        return None

    def get_erp_documents(self, request_id: str) -> list[dict]:
        return []

    def list_suppliers(self) -> list[dict]:
        return [{"id": "S1", "sourceErp": "SAP", "name": "Test Supplier", "status": "active"}]

    def list_requisitions(self) -> list[dict]:
        return []

    def exchange_rates(self) -> dict | None:
        return None


class BoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._saved = portal_data._active
        self.addCleanup(setattr, portal_data, "_active", self._saved)

    def test_sample_mode_is_default(self) -> None:
        portal_data._active = None
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PORTAL_DATA_SOURCE", None)
            self.assertIsInstance(portal_data.portal_data(), portal_data.SampleData)

    def test_unknown_source_fails_clearly(self) -> None:
        portal_data._active = None
        with patch.dict(os.environ, {"PORTAL_DATA_SOURCE": "portal-db"}):
            with self.assertRaisesRegex(RuntimeError, "set_portal_data"):
                portal_data.portal_data()

    def test_sample_reads_are_copies(self) -> None:
        source = portal_data.SampleData()
        req = source.get_request("REQ-0007")
        req["status"] = "Closed"
        req["responses"].clear()
        self.assertEqual(db.REQUESTS["REQ-0007"]["status"], "Locked")
        self.assertEqual(len(db.REQUESTS["REQ-0007"]["responses"]), 3)

    def test_rejects_object_without_interface(self) -> None:
        with self.assertRaises(TypeError):
            portal_data.set_portal_data(object())

    async def test_tools_use_registered_source(self) -> None:
        portal_data.set_portal_data(InMemoryData())
        listed = await _call("list_requests", {})
        self.assertEqual(listed["today"], "2027-01-04")
        self.assertEqual([r["id"] for r in listed["requests"]], ["REQ-9001"])
        self.assertIsNone((await _call("get_request_detail", {"record_id": "REQ-0007"})).get("id"))
        cmp_ = await _call("compare_responses", {"request_id": "REQ-9001"})
        self.assertEqual(cmp_["ranking"][0]["supplierName"], "Test Supplier")
        draft = await _call("draft_award", {"request_id": "REQ-9001"})
        self.assertIs(draft["draft"], True)
        self.assertEqual(draft["erpCallOnConfirm"]["payload"]["supplier"], "S1")


class MixedCurrencySampleTests(unittest.IsolatedAsyncioTestCase):
    async def test_req_0011_provisional_inr_ranking(self) -> None:
        cmp_ = await _call("compare_responses", {"request_id": "REQ-0011"})
        self.assertIs(cmp_["awardable"], True)
        self.assertEqual(cmp_["rankingStatus"], "provisional_fx_ranking")
        self.assertIn("INR, USD", cmp_["message"])
        self.assertEqual([r["rank"] for r in cmp_["ranking"]], [1, 2])

    async def test_req_0011_override_needs_meaningful_reason(self) -> None:
        weak = await _call("draft_award", {"request_id": "REQ-0011",
                                           "supplier_id": "Summit Foundry",
                                           "justification": "hi"})
        self.assertIs(weak["justificationMissing"], True)
        chosen = await _call("draft_award",
                             {"request_id": "REQ-0011", "supplier_id": "Summit Foundry",
                              "justification": "Delivery date drives this order."})
        self.assertIs(chosen["draft"], True)
        self.assertIs(chosen["justificationRequired"], True)
        self.assertIs(chosen["justificationMissing"], False)
        self.assertEqual(chosen["erpCallOnConfirm"]["payload"]["currency"], "USD")


if __name__ == "__main__":
    unittest.main()

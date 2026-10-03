"""Offline tests for currency-aware ranking, override reasons and the packing-list draft.

Run: uv run python -m unittest test_accuracy -v
"""

import copy
import json
import os
import unittest
from unittest.mock import patch

import demo_data as db
import portal_data
from mcp_server import justification_problem, mcp
from prefill import build_draft
from ranking import (
    CONVERTED,
    CURRENCY_REVIEW,
    PROVISIONAL_FX,
    RANKED,
    rank_responses,
    ranking_status,
)


async def _call(name: str, args: dict) -> dict:
    result = await mcp.call_tool(name, args)
    return json.loads("".join(getattr(c, "text", "") for c in result.content))


def _no_rate_request() -> dict:
    """Locked copy of REQ-0007 where Orion Castings quoted in GBP (no demo rate)."""
    req = copy.deepcopy(db.REQUESTS["REQ-0007"])
    req["id"] = "REQ-TEST-NORATE"
    for r in req["responses"]:
        if r["supplierId"] == "10000003":
            r["currency"] = "GBP"
    return req


class ApprovedRates(portal_data.SampleData):
    """Stand-in for a backend that supplies an approved rate."""

    def exchange_rates(self) -> dict:
        return {"baseCurrency": "INR", "ratesToBase": {"INR": 1.0, "USD": 84.2},
                "approved": True, "source": "treasury", "label": "Approved rate"}


class RankingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.before = json.dumps(db.REQUESTS, sort_keys=True, default=str)
        self._saved = portal_data._active
        self.addCleanup(setattr, portal_data, "_active", self._saved)

    def tearDown(self) -> None:
        self.assertEqual(self.before, json.dumps(db.REQUESTS, sort_keys=True, default=str))

    # --- same currency ------------------------------------------------------------
    async def test_same_currency_ranking_unchanged(self) -> None:
        req = db.REQUESTS["REQ-0007"]
        self.assertEqual(ranking_status(req), (RANKED, None))
        rows = rank_responses(req)
        self.assertEqual([r["supplierName"] for r in rows],
                         ["Apex Hydraulics", "Orion Castings", "Delta Precision"])
        self.assertEqual([r["rank"] for r in rows], [1, 2, 3])
        # No conversion: the comparison value is the offer total in its own currency.
        self.assertTrue(all(r["comparisonTotal"] == r["totalPrice"] for r in rows))
        self.assertTrue(all(r["comparisonCurrency"] == "USD" for r in rows))

        cmp_ = await _call("compare_responses", {"request_id": "REQ-0007"})
        self.assertEqual(cmp_["rankingStatus"], RANKED)
        self.assertIs(cmp_["rankingProvisional"], False)
        self.assertIsNone(cmp_["exchangeRate"])
        self.assertNotIn("message", cmp_)

    async def test_same_currency_inr_request(self) -> None:
        cmp_ = await _call("compare_responses", {"request_id": "REQ-0009"})
        self.assertEqual(cmp_["rankingStatus"], RANKED)
        self.assertEqual(
            [(r["supplierName"], r["currency"], r["totalPrice"]) for r in cmp_["ranking"]],
            [("Nordic Gearworks", "INR", 2355000.0), ("Vega Machining", "INR", 2436000.0)])

    # --- USD / INR ----------------------------------------------------------------
    async def test_usd_inr_ranked_provisionally_in_inr(self) -> None:
        cmp_ = await _call("compare_responses", {"request_id": "REQ-0011"})
        self.assertEqual(cmp_["rankingStatus"], PROVISIONAL_FX)
        self.assertIs(cmp_["rankingProvisional"], True)
        rate = cmp_["exchangeRate"]
        self.assertEqual(rate["baseCurrency"], "INR")
        self.assertEqual(rate["ratesToBase"], {"INR": 1.0, "USD": 85.0})
        self.assertIs(rate["approved"], False)
        self.assertIn("not a live or approved rate", rate["label"])
        self.assertIn("Provisional ranking", cmp_["message"])
        self.assertIn("1 USD = 85 INR", cmp_["message"])
        rows = {r["supplierName"]: r for r in cmp_["ranking"]}
        inr, usd = rows["Nordic Gearworks"], rows["Summit Foundry"]
        # Original price kept, converted value added.
        self.assertEqual((inr["currency"], inr["totalPrice"], inr["comparisonTotal"]),
                         ("INR", 225600.0, 225600.0))
        self.assertEqual((usd["currency"], usd["unitPrice"], usd["totalPrice"]),
                         ("USD", 69.5, 2780.0))
        self.assertEqual((usd["comparisonCurrency"], usd["exchangeRateToComparison"],
                          usd["comparisonTotal"]), ("INR", 85.0, 236300.0))
        self.assertEqual((inr["rank"], usd["rank"]), (1, 2))

    async def test_on_time_rule_applies_before_converted_price(self) -> None:
        req = copy.deepcopy(db.REQUESTS["REQ-0011"])
        req["id"] = "REQ-TEST-LATE"
        for r in req["responses"]:
            if r["currency"] == "INR":
                r["promisedDate"] = "2026-11-25"  # after need-by 2026-11-20
        with patch.dict(db.REQUESTS, {"REQ-TEST-LATE": req}):
            cmp_ = await _call("compare_responses", {"request_id": "REQ-TEST-LATE"})
        order = [(r["supplierName"], r["meetsNeedBy"]) for r in cmp_["ranking"]]
        self.assertEqual(order, [("Summit Foundry", True), ("Nordic Gearworks", False)])

    async def test_demo_rate_is_configurable(self) -> None:
        with patch.dict(os.environ, {"DEMO_USD_INR_RATE": "80"}):
            cmp_ = await _call("compare_responses", {"request_id": "REQ-0011"})
        rows = [(r["supplierName"], r["comparisonTotal"]) for r in cmp_["ranking"]]
        # 2,780 USD x 80 = 2,22,400 INR, now cheaper than the 2,25,600 INR offer.
        self.assertEqual(rows, [("Summit Foundry", 222400.0), ("Nordic Gearworks", 225600.0)])
        self.assertIn("1 USD = 80 INR", cmp_["message"])

    async def test_approved_rate_is_not_provisional(self) -> None:
        portal_data.set_portal_data(ApprovedRates())
        cmp_ = await _call("compare_responses", {"request_id": "REQ-0011"})
        self.assertEqual(cmp_["rankingStatus"], CONVERTED)
        self.assertIs(cmp_["rankingProvisional"], False)
        self.assertNotIn("Provisional", cmp_["message"])

    async def test_award_draft_keeps_original_currency(self) -> None:
        auto = await _call("draft_award", {"request_id": "REQ-0011"})
        self.assertIs(auto["draft"], True)
        self.assertEqual(auto["awardTo"]["supplierName"], "Nordic Gearworks")
        self.assertIs(auto["rankingProvisional"], True)
        self.assertTrue(any("Provisional ranking" in w for w in auto["warnings"]))
        self.assertEqual(auto["erpCallOnConfirm"]["payload"]["currency"], "INR")
        self.assertEqual(auto["erpCallOnConfirm"]["payload"]["unitPrice"], 5640.0)

        usd = await _call("draft_award", {"request_id": "REQ-0011", "supplier_id": "SUP000047",
                                          "justification": "Earlier delivery needed for line start"})
        self.assertIs(usd["justificationRequired"], True)
        self.assertIs(usd["justificationMissing"], False)
        payload = usd["erpCallOnConfirm"]["payload"]
        self.assertEqual((payload["currency"], payload["unitPrice"]), ("USD", 69.5))

    async def test_currency_without_rate_is_not_ranked(self) -> None:
        fixture = _no_rate_request()
        with patch.dict(db.REQUESTS, {"REQ-TEST-NORATE": fixture}):
            status, message = ranking_status(fixture)
            self.assertEqual(status, CURRENCY_REVIEW)
            self.assertIn("no exchange rate is available for GBP", message)
            cmp_ = await _call("compare_responses", {"request_id": "REQ-TEST-NORATE"})
            self.assertTrue(all(r["rank"] is None for r in cmp_["ranking"]))
            self.assertTrue(all(r["comparisonTotal"] is None for r in cmp_["ranking"]))
            auto = await _call("draft_award", {"request_id": "REQ-TEST-NORATE"})
            self.assertIs(auto["draft"], False)
            chosen = await _call("draft_award",
                                 {"request_id": "REQ-TEST-NORATE", "supplier_id": "10000001"})
            self.assertIsNone(chosen["rank"])
            self.assertIs(chosen["justificationMissing"], True)


class JustificationTests(unittest.IsolatedAsyncioTestCase):
    def test_meaningless_reasons_rejected(self) -> None:
        for text in ("", "   ", "hi", "Hi!", "ok", "test", "hi hi hi hi hi hi",
                     "test ok fine", "asdf", "n/a", "because reason", "12345678901234567"):
            with self.subTest(text=text):
                self.assertIsNotNone(justification_problem(text))

    def test_meaningful_reasons_accepted(self) -> None:
        for text in ("Only supplier with the approved tooling",
                     "Earlier delivery needed for line start",
                     "Sole qualified source for this revision.",
                     "\u0917\u0941\u0923\u0935\u0924\u094d\u0924\u093e \u0914\u0930 "
                     "\u0938\u092e\u092f \u092a\u0930 \u0921\u093f\u0932\u0940\u0935\u0930\u0940"):
            with self.subTest(text=text):
                self.assertIsNone(justification_problem(text))

    async def test_hi_does_not_satisfy_required_reason(self) -> None:
        draft = await _call("draft_award", {"request_id": "REQ-0007",
                                            "supplier_id": "Delta Precision",
                                            "justification": "hi"})
        self.assertIs(draft["justificationRequired"], True)
        self.assertIs(draft["justificationMissing"], True)
        self.assertIn("too short or generic", draft["justificationProblem"])

    async def test_top_pick_needs_no_reason(self) -> None:
        draft = await _call("draft_award", {"request_id": "REQ-0007"})
        self.assertIs(draft["justificationMissing"], False)
        self.assertIsNone(draft["justificationProblem"])


class PrefillDraftTests(unittest.TestCase):
    FIELDS = {"shipDate": "2026-10-14", "carrier": "DHL Freight",
              "trackingNumber": "DHLF-7734-2291", "quantity": 30,
              "lotNumbers": ["LOT-A1"], "unreadableFields": []}

    def test_matching_quantity(self) -> None:
        d = build_draft(dict(self.FIELDS), "packing.pdf", po_quantity=30)
        self.assertEqual(d["quantityCheck"]["status"], "match")
        self.assertIs(d["quantityMismatch"], False)
        self.assertEqual(d["unreadableFields"], [])
        self.assertEqual(d["manualEntryRequired"], [])
        self.assertEqual(d["poQuantitySource"], "manual_sample_input")
        self.assertIn("not fetched from SAP, LN or a database", d["poQuantityNote"])
        self.assertIs(d["draft"], True)

    def test_mismatching_quantity_is_a_review_warning(self) -> None:
        d = build_draft(dict(self.FIELDS), "packing.pdf", po_quantity=50)
        self.assertEqual(d["quantityCheck"]["status"], "mismatch")
        self.assertIs(d["quantityMismatch"], True)
        self.assertIs(d["draft"], True)  # still a usable draft, not rejected
        msg = d["quantityCheck"]["message"]
        self.assertIn("Review", msg)
        self.assertIn("not a decision that the shipment is invalid", msg)
        self.assertEqual(d["fields"]["quantity"], 30)  # extracted value is kept

    def test_unreadable_fields_need_manual_entry(self) -> None:
        fields = dict(self.FIELDS, carrier="", quantity=-1, lotNumbers=[],
                      unreadableFields=["trackingNumber"])
        d = build_draft(fields, "scan.png", po_quantity=30)
        self.assertEqual(d["unreadableFields"],
                         ["carrier", "trackingNumber", "quantity", "lotNumbers"])
        self.assertEqual([m["label"] for m in d["manualEntryRequired"]],
                         ["Carrier", "Tracking number", "Quantity", "Lot / serial numbers"])
        self.assertIsNone(d["fields"]["quantity"])  # -1 placeholder is not shown as a value
        self.assertIsNone(d["fields"]["trackingNumber"])
        self.assertEqual(d["fields"]["shipDate"], "2026-10-14")
        self.assertEqual(d["quantityCheck"]["status"], "not_checked")
        self.assertIs(d["quantityMismatch"], False)

    def test_no_po_quantity_entered(self) -> None:
        d = build_draft(dict(self.FIELDS), "packing.pdf")
        self.assertEqual(d["quantityCheck"]["status"], "not_checked")
        self.assertIsNone(d["poQuantitySource"])
        self.assertIsNone(d["poQuantityNote"])

    def test_draft_makes_no_erp_or_posting_claim(self) -> None:
        d = build_draft(dict(self.FIELDS), "packing.pdf", po_quantity=50)
        self.assertIn("nothing has been created or posted", d["note"])
        # The disclaimer itself says "not fetched from SAP"; check everything else.
        text = json.dumps(dict(d, poQuantityNote=None)).lower()
        for claim in ("fetched from sap", "fetched from ln", "from the database",
                      "shipment created", "shipment posted", "posted to"):
            self.assertNotIn(claim, text)

    def test_negative_po_quantity_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_draft(dict(self.FIELDS), "packing.pdf", po_quantity=-5)


if __name__ == "__main__":
    unittest.main()

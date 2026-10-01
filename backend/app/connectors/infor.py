from copy import deepcopy
from itertools import count

from ..db import now
from .base import ERPConnector

# Native Infor LN-style payloads.
ITEMS = [
    {"item": "ITEM001", "description": "Hex Bolt M8 x 40 (Zinc)", "onhand": 1200, "warehouse": "WH-EAST"},
    {"item": "ITEM002", "description": "Steel Sheet 2mm 1x2m", "onhand": 85, "warehouse": "WH-EAST"},
    {"item": "ITEM003", "description": "Hydraulic Pump HP-200", "onhand": 14, "warehouse": "WH-WEST"},
]
SUPPLIERS = [
    {"bpid": "BP-001", "name": "ABC Industrial Supplies", "email": "sales@abc-industrial.example", "phone": "+1 555 0101", "address": "12 Foundry Rd, Detroit, MI"},
    {"bpid": "BP-002", "name": "Globex Components", "email": "orders@globex.example", "phone": "+1 555 0102", "address": "400 Market St, Austin, TX"},
]
ORDERS = [
    {"orno": "LN-700001", "bpid": "BP-001", "lines": [{"item": "ITEM001", "qty": 500, "price": 0.12}]},
]
RECEIPTS: list[dict] = []  # warehouse receipts (inbound advice + receipt status)
STOCK_MOVEMENTS: list[dict] = []  # inventory transactions; blocked = quarantine location
INVOICE_HOLDS: list[dict] = []  # accounts-payable holds

_INITIAL = deepcopy(ORDERS)
_seq = count(700002)
_rcp = count(9000001)
_trn = count(1)
_hld = count(1)


def _onhand(item: str, qty: int) -> None:
    for i in ITEMS:
        if i["item"] == item:
            i["onhand"] += qty
            return
    ITEMS.append({"item": item, "description": item, "onhand": qty, "warehouse": "WH-EAST"})


class MockInforConnector(ERPConnector):
    name = "infor"

    def reset(self):
        global _seq, _rcp, _trn, _hld
        ORDERS[:] = deepcopy(_INITIAL)
        RECEIPTS.clear()
        STOCK_MOVEMENTS.clear()
        INVOICE_HOLDS.clear()
        _seq, _rcp, _trn, _hld = count(700002), count(9000001), count(1), count(1)

    def raw_items(self):
        return ITEMS

    def raw_suppliers(self):
        return SUPPLIERS

    def raw_orders(self):
        return ORDERS

    def raw_receipts(self):
        return RECEIPTS

    def raw_stock_movements(self):
        return STOCK_MOVEMENTS

    def raw_invoice_holds(self):
        return INVOICE_HOLDS

    def raw_create_order(self, payload: dict) -> dict:
        record = {"orno": f"LN-{next(_seq)}", **payload}
        ORDERS.append(record)
        return record

    def list_items(self):
        return [
            {"item_code": i["item"], "description": i["description"], "stock_quantity": i["onhand"], "warehouse": i["warehouse"]}
            for i in ITEMS
        ]

    def list_suppliers(self):
        return [
            {"supplier_name": s["name"], "email": s["email"], "phone": s["phone"], "address": s["address"]}
            for s in SUPPLIERS
        ]

    def list_purchase_orders(self):
        names = {s["bpid"]: s["name"] for s in SUPPLIERS}
        return [
            {
                "po_number": o["orno"],
                "supplier": names.get(o["bpid"], o["bpid"]),
                "items": [{"item_code": l["item"], "quantity": l["qty"], "unit_price": l["price"]} for l in o["lines"]],
            }
            for o in ORDERS
        ]

    def push_purchase_order(self, po: dict) -> dict:
        rec = self.raw_create_order(
            {
                "bpid": "BP-001",
                "lines": [{"item": i["item_code"], "qty": i["quantity"], "price": i["unit_price"]} for i in po["items"]],
                "ref": po["po_number"],
            }
        )
        return {"erp": self.name, "erp_reference": rec["orno"]}

    def create_inbound_delivery(self, po, shipment):
        rcno = f"RCV-{next(_rcp)}"
        RECEIPTS.append(
            {
                "rcno": rcno,
                "orno": po.get("erp_reference"),
                "ref": po["po_number"],
                "asn": shipment["shipment_no"],
                "tracking": shipment.get("tracking_no", ""),
                "lines": [{"item": i["item_code"], "expected": i["quantity_shipped"]} for i in shipment["items"]],
                "status": "Expected",
                "created": now(),
            }
        )
        return {"erp_inbound_ref": rcno}

    def _movement(self, location, po, shipment, lines, note):
        trn = f"TRN-{next(_trn):05d}"
        STOCK_MOVEMENTS.append(
            {
                "trn": trn,
                "orno": po.get("erp_reference"),
                "rcno": shipment.get("erp_inbound_ref"),
                "location": location,  # available | quarantine
                "lines": [{"item": ln["item_code"], "qty": ln["quantity"]} for ln in lines],
                "note": note,
                "created": now(),
            }
        )
        for r in RECEIPTS:
            if r["rcno"] == shipment.get("erp_inbound_ref"):
                r["status"] = "Received" if location == "available" else "Quarantined"
        return trn

    def release_stock(self, po, shipment, lines):
        for ln in lines:
            _onhand(ln["item_code"], ln["quantity"])
        return {"movement_ref": self._movement("available", po, shipment, lines, "Receipt to available stock")}

    def quarantine_stock(self, po, shipment, lines, reason):
        return {"movement_ref": self._movement("quarantine", po, shipment, lines, f"Rejected at inspection: {reason}")}

    def set_invoice_hold(self, po, hold, reason=""):
        ref = po.get("erp_reference")
        for h in INVOICE_HOLDS:
            if h["orno"] == ref and h["active"]:
                h["active"], h["released"] = False, now()
        if hold:
            INVOICE_HOLDS.append({"hold": f"HLD-{next(_hld):04d}", "orno": ref, "reason": reason, "active": True, "created": now()})
        return {"hold_ref": ref}

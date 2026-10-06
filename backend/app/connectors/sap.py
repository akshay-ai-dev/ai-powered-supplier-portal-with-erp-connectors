from copy import deepcopy
from itertools import count

from ..db import now
from .base import ERPConnector

# Native SAP-style payloads (MATNR / LIFNR / EBELN naming).
MATERIALS = [
    {"MATNR": "ITEM001", "MAKTX": "Hex Bolt M8 x 40 (Zinc)", "LABST": 1200, "WERKS": "PLANT-1000"},
    {"MATNR": "ITEM002", "MAKTX": "Steel Sheet 2mm 1x2m", "LABST": 85, "WERKS": "PLANT-1000"},
    {"MATNR": "ITEM003", "MAKTX": "Hydraulic Pump HP-200", "LABST": 14, "WERKS": "PLANT-2000"},
    {"MATNR": "ITEM004", "MAKTX": "Bearing 6204-2RS", "LABST": 640, "WERKS": "PLANT-1000"},
    {"MATNR": "ITEM005", "MAKTX": "Control Panel CP-50", "LABST": 6, "WERKS": "PLANT-2000"},
    {"MATNR": "ITEM006", "MAKTX": "Industrial Lubricant 20L", "LABST": 42, "WERKS": "PLANT-3000"},
    {"MATNR": "ITEM007", "MAKTX": "Copper Wire 2.5mm (100m)", "LABST": 210, "WERKS": "PLANT-3000"},
    {"MATNR": "ITEM008", "MAKTX": "Safety Gloves (Box of 50)", "LABST": 0, "WERKS": "PLANT-1000"},
]
VENDORS = [
    {
        "LIFNR": "100001",
        "NAME1": "ABC Industrial Supplies",
        "SMTP_ADDR": "sales@abc-industrial.example",
        "TELF1": "+1 555 0101",
        "STRAS": "12 Foundry Rd, Detroit, MI",
    },
    {
        "LIFNR": "100002",
        "NAME1": "Globex Components",
        "SMTP_ADDR": "orders@globex.example",
        "TELF1": "+1 555 0102",
        "STRAS": "400 Market St, Austin, TX",
    },
    {
        "LIFNR": "100003",
        "NAME1": "Northwind Metals",
        "SMTP_ADDR": "hello@northwind.example",
        "TELF1": "+1 555 0103",
        "STRAS": "88 Harbor Ave, Seattle, WA",
    },
    {
        "LIFNR": "100004",
        "NAME1": "Initech Electrical",
        "SMTP_ADDR": "supply@initech.example",
        "TELF1": "+1 555 0104",
        "STRAS": "1 Circuit Way, San Jose, CA",
    },
]
PURCHASE_ORDERS = [
    {
        "EBELN": "4500000001",
        "LIFNR": "100001",
        "ITEMS": [{"MATNR": "ITEM001", "MENGE": 500, "NETPR": 0.12}],
    },
]
# Fulfilment documents created by the warehouse flow
INBOUND_DELIVERIES: list[dict] = []  # LIKP/LIPS: inbound delivery header + items
STOCK_MOVEMENTS: list[
    dict
] = []  # MSEG: 101 = goods receipt to unrestricted, 103/350 = to blocked (quarantine)
INVOICE_BLOCKS: list[dict] = []  # RBKP payment block (ZLSPR)

_INITIAL = deepcopy(PURCHASE_ORDERS)
_seq = count(4500000002)
_dlv = count(180000001)
_mat = count(5000000001)
_blk = count(1)


def _stock(matnr: str, qty: int) -> None:
    for m in MATERIALS:
        if m["MATNR"] == matnr:
            m["LABST"] += qty
            return
    MATERIALS.append({"MATNR": matnr, "MAKTX": matnr, "LABST": qty, "WERKS": "PLANT-1000"})


class MockSapConnector(ERPConnector):
    name = "sap"

    def reset(self):
        global _seq, _dlv, _mat, _blk
        PURCHASE_ORDERS[:] = deepcopy(_INITIAL)
        INBOUND_DELIVERIES.clear()
        STOCK_MOVEMENTS.clear()
        INVOICE_BLOCKS.clear()
        _seq, _dlv, _mat, _blk = count(4500000002), count(180000001), count(5000000001), count(1)

    # --- native (raw) access used by /mock/sap/* ---
    def raw_materials(self):
        return MATERIALS

    def raw_vendors(self):
        return VENDORS

    def raw_purchase_orders(self):
        return PURCHASE_ORDERS

    def raw_inbound_deliveries(self):
        return INBOUND_DELIVERIES

    def raw_stock_movements(self):
        return STOCK_MOVEMENTS

    def raw_invoice_blocks(self):
        return INVOICE_BLOCKS

    def raw_create_purchase_order(self, payload: dict) -> dict:
        record = {"EBELN": str(next(_seq)), **payload}  # noqa
        PURCHASE_ORDERS.append(record)
        return record

    # --- normalized contract ---
    def list_items(self):
        return [
            {
                "item_code": m["MATNR"],
                "description": m["MAKTX"],
                "stock_quantity": m["LABST"],
                "warehouse": m["WERKS"],
            }
            for m in MATERIALS
        ]

    def list_suppliers(self):
        return [
            {
                "supplier_name": v["NAME1"],
                "email": v["SMTP_ADDR"],
                "phone": v["TELF1"],
                "address": v["STRAS"],
            }
            for v in VENDORS
        ]

    def list_purchase_orders(self):
        vendors = {v["LIFNR"]: v["NAME1"] for v in VENDORS}
        return [
            {
                "po_number": p["EBELN"],
                "supplier": vendors.get(p["LIFNR"], p["LIFNR"]),
                "items": [
                    {"item_code": i["MATNR"], "quantity": i["MENGE"], "unit_price": i["NETPR"]}
                    for i in p["ITEMS"]
                ],
            }
            for p in PURCHASE_ORDERS
        ]

    def push_purchase_order(self, po: dict) -> dict:
        rec = self.raw_create_purchase_order(
            {
                "LIFNR": "100001",
                "ITEMS": [
                    {"MATNR": i["item_code"], "MENGE": i["quantity"], "NETPR": i["unit_price"]}
                    for i in po["items"]
                ],
                "REF": po["po_number"],
            }
        )
        return {"erp": self.name, "erp_reference": rec["EBELN"]}

    def create_inbound_delivery(self, po, shipment):
        vbeln = str(next(_dlv))
        INBOUND_DELIVERIES.append(
            {
                "VBELN": vbeln,
                "EBELN": po.get("erp_reference"),
                "REF_PO": po["po_number"],
                "LIFEX": shipment["shipment_no"],  # vendor's delivery note number
                "TRAID": shipment.get("tracking_no", ""),
                "ITEMS": [
                    {"MATNR": i["item_code"], "LFIMG": i["quantity_shipped"]}
                    for i in shipment["items"]
                ],
                "STATUS": "OPEN",
                "ERDAT": now(),
            }
        )
        return {"erp_inbound_ref": vbeln}

    def _movement(self, movement_type, po, shipment, lines, note=""):
        doc = str(next(_mat))
        STOCK_MOVEMENTS.append(
            {
                "MBLNR": doc,
                "BWART": movement_type,
                "EBELN": po.get("erp_reference"),
                "VBELN": shipment.get("erp_inbound_ref"),
                "ITEMS": [{"MATNR": ln["item_code"], "MENGE": ln["quantity"]} for ln in lines],
                "NOTE": note,
                "BUDAT": now(),
            }
        )
        for d in INBOUND_DELIVERIES:
            if d["VBELN"] == shipment.get("erp_inbound_ref"):
                d["STATUS"] = "GR POSTED" if movement_type == "101" else "BLOCKED"
        return doc

    def release_stock(self, po, shipment, lines):
        for ln in lines:
            _stock(ln["item_code"], ln["quantity"])
        return {
            "movement_ref": self._movement(
                "101", po, shipment, lines, "Goods receipt to unrestricted-use stock"
            )
        }

    def quarantine_stock(self, po, shipment, lines, reason):
        # Blocked stock is not added to LABST (unrestricted); it is only booked as a movement.
        return {
            "movement_ref": self._movement(
                "350", po, shipment, lines, f"Blocked stock (quarantine): {reason}"
            )
        }

    def set_invoice_hold(self, po, hold, reason=""):
        ref = po.get("erp_reference")
        for b in INVOICE_BLOCKS:
            if b["EBELN"] == ref and b["ACTIVE"]:
                b["ACTIVE"], b["RELEASED"] = False, now()
        if hold:
            INVOICE_BLOCKS.append(
                {
                    "BLOCK_ID": f"B{next(_blk):04d}",
                    "EBELN": ref,
                    "ZLSPR": "R",
                    "REASON": reason,
                    "ACTIVE": True,
                    "CREATED": now(),
                }
            )
        return {"hold_ref": ref}

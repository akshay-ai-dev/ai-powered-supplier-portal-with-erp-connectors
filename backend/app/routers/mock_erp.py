"""Mock SAP and Infor LN endpoints. Unauthenticated on purpose: they stand in for external systems."""

from typing import Any

from fastapi import APIRouter, Body

from ..connectors import get_connector
from ..connectors.infor import MockInforConnector
from ..connectors.sap import MockSapConnector

sap = APIRouter(prefix="/mock/sap", tags=["Mock SAP"])
infor = APIRouter(prefix="/mock/infor", tags=["Mock Infor LN"])

_sap: MockSapConnector = get_connector("sap")  # type: ignore[assignment]
_infor: MockInforConnector = get_connector("infor")  # type: ignore[assignment]


@sap.get("/materials")
def sap_materials():
    return _sap.raw_materials()


@sap.get("/vendors")
def sap_vendors():
    return _sap.raw_vendors()


@sap.get("/purchase-orders")
def sap_pos():
    return _sap.raw_purchase_orders()


@sap.post("/purchase-orders", status_code=201)
def sap_create_po(
    payload: dict[str, Any] = Body(
        ...,
        examples=[{"LIFNR": "100001", "ITEMS": [{"MATNR": "ITEM001", "MENGE": 10, "NETPR": 0.12}]}],
    ),
):
    return _sap.raw_create_purchase_order(payload)


@sap.get("/inbound-deliveries")
def sap_inbound():
    return _sap.raw_inbound_deliveries()


@sap.get("/stock-movements")
def sap_movements():
    return _sap.raw_stock_movements()


@sap.get("/invoice-blocks")
def sap_blocks():
    return _sap.raw_invoice_blocks()


@infor.get("/receipts")
def infor_receipts():
    return _infor.raw_receipts()


@infor.get("/stock-movements")
def infor_movements():
    return _infor.raw_stock_movements()


@infor.get("/invoice-holds")
def infor_holds():
    return _infor.raw_invoice_holds()


@infor.get("/items")
def infor_items():
    return _infor.raw_items()


@infor.get("/suppliers")
def infor_suppliers():
    return _infor.raw_suppliers()


@infor.get("/orders")
def infor_orders():
    return _infor.raw_orders()


@infor.post("/orders", status_code=201)
def infor_create_order(
    payload: dict[str, Any] = Body(
        ..., examples=[{"bpid": "BP-001", "lines": [{"item": "ITEM001", "qty": 10, "price": 0.12}]}]
    ),
):
    return _infor.raw_create_order(payload)

"""Read-only data boundary between the AI slice and the portal.

Every MCP tool, the ranking code and the grounding checks read portal data only
through the `PortalData` interface below. This demo ships one implementation,
`SampleData`, backed by `demo_data.py`. At integration the team backend provides
its own implementation (portal database services plus SAP / Infor LN connector
reads) and registers it with `set_portal_data()`; tool names and response shapes
stay the same.

The interface is deliberately read-only: there is no create/update/post method,
so nothing reached through the AI can write to the portal or an ERP.

Record shapes (plain dicts) are documented in INTEGRATION.md.
"""

import copy
import os
from typing import Protocol, runtime_checkable

import demo_data


@runtime_checkable
class PortalData(Protocol):
    """Read operations the AI slice needs. Return copies; callers may not mutate."""

    def today(self) -> str:
        """Business date used for the request list (YYYY-MM-DD)."""

    def list_requests(self) -> list[dict]:
        """All sourcing requests the current user may see."""

    def get_request(self, request_id: str) -> dict | None:
        """One sourcing request by portal ID (e.g. REQ-0007), or None."""

    def get_shipment(self, shipment_id: str) -> dict | None:
        """One shipment by portal ID (e.g. SHP-0012), including its inspection, or None."""

    def get_erp_documents(self, request_id: str) -> list[dict]:
        """ERP documents linked to a request (requisition, PO, delivery, receipt, ...)."""

    def list_suppliers(self) -> list[dict]:
        """Supplier master records across both ERPs, with status active/blocked."""

    def list_requisitions(self) -> list[dict]:
        """ERP purchase requisitions that can be turned into sourcing requests."""

    def exchange_rates(self) -> dict | None:
        """Rates for comparing offers in different currencies, or None if unavailable:
        {baseCurrency, ratesToBase: {currency: units of base per 1 unit}, approved: bool,
        source, label}. approved=False means the ranking it produces is provisional."""


class SampleData:
    """Sample-data mode: reads the fictional records in demo_data.py.

    Reads the module dictionaries at call time (so tests can patch them) and returns
    deep copies, so no caller can change the sample records.
    """

    def today(self) -> str:
        return demo_data.TODAY

    def list_requests(self) -> list[dict]:
        return copy.deepcopy(list(demo_data.REQUESTS.values()))

    def get_request(self, request_id: str) -> dict | None:
        return copy.deepcopy(demo_data.REQUESTS.get(request_id))

    def get_shipment(self, shipment_id: str) -> dict | None:
        return copy.deepcopy(demo_data.SHIPMENTS.get(shipment_id))

    def get_erp_documents(self, request_id: str) -> list[dict]:
        return copy.deepcopy(demo_data.ERP_DOCUMENTS.get(request_id, []))

    def list_suppliers(self) -> list[dict]:
        return copy.deepcopy(demo_data.SUPPLIERS)

    def list_requisitions(self) -> list[dict]:
        return copy.deepcopy(demo_data.REQUISITIONS)

    def exchange_rates(self) -> dict | None:
        rates = copy.deepcopy(demo_data.DEMO_EXCHANGE_RATE)
        override = os.environ.get("DEMO_USD_INR_RATE", "").strip()
        if override:
            try:
                value = float(override)
            except ValueError:
                value = 0.0
            if value <= 0:
                raise RuntimeError("DEMO_USD_INR_RATE must be a positive number")
            rates["ratesToBase"]["USD"] = value
        usd = rates["ratesToBase"]["USD"]
        return dict(
            rates,
            approved=False,
            source="demo",
            label=f"Demo exchange rate: 1 USD = {usd:g} INR (sample data, not a live "
                  "or approved rate)",
        )


_SOURCES = {"sample": SampleData}
_active: PortalData | None = None


def set_portal_data(source: PortalData) -> None:
    """Register the implementation to use (the team backend calls this at startup)."""
    if not isinstance(source, PortalData):
        raise TypeError("source must implement the PortalData interface")
    global _active
    _active = source


def portal_data() -> PortalData:
    """The active data source. Defaults to PORTAL_DATA_SOURCE (only 'sample' ships here)."""
    global _active
    if _active is None:
        name = (os.environ.get("PORTAL_DATA_SOURCE") or "sample").strip().lower()
        if name not in _SOURCES:
            raise RuntimeError(
                f"PORTAL_DATA_SOURCE={name!r} is not available in this demo. Only 'sample' "
                "ships here; the team backend must register its own PortalData "
                "implementation with portal_data.set_portal_data()."
            )
        _active = _SOURCES[name]()
    return _active


# Small helpers shared by the tools, ranking and grounding code.

def supplier_by_id(supplier_id: str) -> dict | None:
    return next((s for s in portal_data().list_suppliers() if s["id"] == supplier_id), None)


def supplier_name(supplier_id: str) -> str:
    s = supplier_by_id(supplier_id)
    return s["name"] if s else supplier_id


def find_supplier(key: str) -> dict | None:
    """Match a supplier by ID or exact name (case-insensitive)."""
    key = key.strip().lower()
    return next(
        (s for s in portal_data().list_suppliers() if key in (s["id"].lower(), s["name"].lower())),
        None,
    )

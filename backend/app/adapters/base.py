"""Adapter interface shared by mock and real ERP adapters (SRS §5.2).

The portal and AI never talk to an ERP directly: they call the connector core,
which routes to the adapter for the record's source ERP.

Every write takes an idempotency `key`; repeating a call with the same key
returns the original document instead of creating a new one.

TODO: replace the `Any` placeholders with the canonical Pydantic models from
`app.core` once they are defined (SRS §7).
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class ErpAdapter(ABC):
    @abstractmethod
    def list_suppliers(self, since: datetime | None = None) -> list[Any]:
        """-> Supplier[]"""

    @abstractmethod
    def list_parts(self, since: datetime | None = None) -> list[Any]:
        """-> Part[] (with BOM lines)"""

    @abstractmethod
    def list_open_requisitions(self, since: datetime | None = None) -> list[Any]:
        """-> Requisition[]"""

    @abstractmethod
    def create_purchase_order(self, award: Any, key: str) -> dict[str, str]:
        """-> {poNumber}"""

    @abstractmethod
    def create_inbound_delivery(self, shipment: Any, key: str) -> dict[str, str]:
        """-> {deliveryNumber}"""

    @abstractmethod
    def post_goods_receipt(self, arrival: Any, key: str) -> dict[str, str]:
        """-> {receiptNumber, inspectionRef}"""

    @abstractmethod
    def post_quality_decision(self, inspection: Any, key: str) -> dict[str, str]:
        """-> {decisionRef, stockStatus}"""

    @abstractmethod
    def set_invoice_hold(self, po_number: str, reason: str, key: str) -> dict[str, str]:
        """-> {holdRef}"""

    @abstractmethod
    def get_document(self, doc_type: str, number: str) -> Any:
        """-> ErpDocument"""

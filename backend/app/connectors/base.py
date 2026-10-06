from abc import ABC, abstractmethod


class ERPConnector(ABC):
    """ERP-agnostic contract. Real SAP S/4HANA / Infor LN connectors implement
    this interface and return the same normalized shapes as the mocks."""

    name: str

    def reset(self) -> None:  # noqa: B027 - deliberately not abstract: real connectors have nothing to reset
        """Restore the connector's mock state (no-op for real connectors)."""

    @abstractmethod
    def list_items(self) -> list[dict]:
        """Normalized: item_code, description, stock_quantity, warehouse."""

    @abstractmethod
    def list_suppliers(self) -> list[dict]:
        """Normalized: supplier_name, email, phone, address."""

    @abstractmethod
    def list_purchase_orders(self) -> list[dict]:
        """Normalized: po_number, supplier, items[{item_code, quantity, unit_price}]."""

    @abstractmethod
    def push_purchase_order(self, po: dict) -> dict:
        """Send a PO to the ERP; returns {erp, erp_reference}."""

    # ---- fulfilment: what the warehouse does against the ERP ----
    @abstractmethod
    def create_inbound_delivery(self, po: dict, shipment: dict) -> dict:
        """Announce an incoming shipment (ASN). Returns {erp_inbound_ref}."""

    @abstractmethod
    def release_stock(self, po: dict, shipment: dict, lines: list[dict]) -> dict:
        """Goods receipt into available stock. lines: [{item_code, quantity}]. Returns {movement_ref}."""

    @abstractmethod
    def quarantine_stock(self, po: dict, shipment: dict, lines: list[dict], reason: str) -> dict:
        """Receive into blocked/quarantine stock (not available). Returns {movement_ref}."""

    @abstractmethod
    def set_invoice_hold(self, po: dict, hold: bool, reason: str = "") -> dict:
        """Block or release supplier invoice payment for the PO. Returns {hold_ref}."""

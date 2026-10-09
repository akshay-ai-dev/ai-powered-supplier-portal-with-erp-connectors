"""Supplier packing-list pre-fill for the shipment form.

A supplier uploads a packing-list PDF/image for one of their purchase orders and gets back a reviewable
draft (ship date, carrier, tracking/lot/serial numbers, shipped quantity and unit). It creates no
shipment, attachment or ERP transaction. A companion endpoint compares a reviewed shipped quantity
against the PO using backend data only. Access is limited to the supplier who owns the PO (the same
visibility the PO service enforces).
"""

import sqlite3

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field

from app.config import settings
from app.db import db_dep
from app.deps import current_user
from app.services import purchase_orders as po_svc
from app.services.errors import Forbidden

from . import compare, extractor

router = APIRouter(prefix="/api/extraction-prefill", tags=["Extraction Prefill"])


def _supplier_po(conn: sqlite3.Connection, user: dict, po_id: int) -> dict:
    """The PO, only for the supplier who owns it. get_po already hides POs a user may not see."""
    if user.get("role") != "supplier" or not user.get("supplier_id"):
        raise Forbidden("Only the assigned supplier can pre-fill a shipment from a document")
    return po_svc.get_po(conn, user, po_id)  # NotFound if it is not this supplier's PO


@router.post(
    "/shipments/{po_id}",
    summary="Extract a packing-list draft for one of your purchase orders (supplier; saves nothing)",
)
def extract_for_shipment(
    po_id: int,
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    _supplier_po(conn, user, po_id)  # authorize before any upload read or network call
    if not settings.openai_api_key:
        from app.services.errors import DomainError

        raise DomainError(
            "Document extraction is not configured (no OPENAI_API_KEY). You can still fill the form yourself.",
            503,
        )
    data = file.file.read(extractor.MAX_BYTES + 1)  # never read more than the limit + 1 byte
    return extractor.extract(file.filename or "file", data, file.content_type)


class CompareIn(BaseModel):
    shipped_quantity: float | None = Field(
        default=None,
        description="The reviewed shipped quantity, or null if there is no single total",
    )
    item_code: str | None = Field(
        default=None,
        description="Which PO item the quantity is for (needed when the order has several)",
    )


@router.post(
    "/shipments/{po_id}/compare",
    summary="Compare a reviewed shipped quantity against the PO (supplier; backend PO data only)",
)
def compare_for_shipment(
    po_id: int,
    body: CompareIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    po = _supplier_po(conn, user, po_id)
    return compare.compare_quantity(po, body.shipped_quantity, body.item_code)

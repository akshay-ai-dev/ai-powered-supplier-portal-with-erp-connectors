import sqlite3

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse

from ..db import db_dep
from ..deps import current_user, require_roles
from ..schemas import ArrivalIn, InspectionIn, ShipmentCreate
from ..services import attachments as attachments_svc
from ..services import purchase_orders as po_svc
from ..services import shipments as ship_svc

router = APIRouter(
    prefix="/api",
    tags=["Shipments & Receiving"],
    dependencies=[Depends(require_roles("buyer", "supplier", "inspector"))],
)


@router.get(
    "/shipments",
    summary="Shipments you may see (supplier: own, buyer: own POs, inspector: assigned scope)",
)
def list_shipments(
    status: str | None = None,
    view: str | None = Query(
        None,
        pattern="^(arriving_today|overdue|inspected_today)$",
        description="What the inspector dashboard counts: expected today and not arrived, expected earlier and not arrived, or decided today",
    ),
    tz: int = Query(
        0,
        ge=-840,
        le=840,
        description="Your offset from UTC in minutes (east is positive), so that 'today' is your day",
    ),
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return ship_svc.list_shipments(conn, user, status, view=view, tz_minutes=tz)


@router.get("/shipments/{shipment_id}")
def get_shipment(
    shipment_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return ship_svc.get_shipment(conn, user, shipment_id)


@router.get("/purchase-orders/{po_id}/shipments")
def po_shipments(
    po_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    po_svc.get_po(conn, user, po_id)  # same visibility rules as the PO itself
    return ship_svc.list_shipments(conn, user, po_id=po_id)


@router.get(
    "/purchase-orders/{po_id}/to-ship",
    summary="Delivery progress per item, and the inspected shipments with faulty, missing or rejected units still to replace",
)
def to_ship(
    po_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    po = po_svc.get_po(conn, user, po_id)  # same visibility rules as the PO itself
    return ship_svc.to_ship(conn, po)


@router.post(
    "/purchase-orders/{po_id}/shipments",
    status_code=201,
    summary="Supplier ships an approved order",
)
def create_shipment(
    po_id: int,
    body: ShipmentCreate,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return ship_svc.create_shipment(conn, user, po_id, body.model_dump())


@router.post(
    "/shipments/{shipment_id}/files",
    status_code=201,
    summary="kind=packing_list (supplier) or photo (inspector)",
)
def upload_shipment_file(
    shipment_id: int,
    kind: str,
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    data = file.file.read(attachments_svc.MAX_BYTES + 1)
    return ship_svc.add_file(
        conn, user, shipment_id, kind, file.filename or "file", data, file.content_type
    )


@router.get("/shipment-files/{file_id}/download")
def download_shipment_file(
    file_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    row, path = ship_svc.open_file(conn, user, file_id)
    return FileResponse(
        path,
        filename=row["filename"],
        media_type="application/octet-stream",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.post(
    "/shipments/{shipment_id}/arrival", summary="Inspector records what physically arrived"
)
def record_arrival(
    shipment_id: int,
    body: ArrivalIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return ship_svc.record_arrival(
        conn, user, shipment_id, [ln.model_dump() for ln in body.lines], body.notes
    )


@router.post(
    "/shipments/{shipment_id}/inspection",
    summary="Inspector approves (release stock) or rejects (quarantine + invoice hold)",
)
def inspect_shipment(
    shipment_id: int,
    body: InspectionIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return ship_svc.inspect(
        conn,
        user,
        shipment_id,
        body.decision,
        body.notes,
        body.reason,
        body.checks,
        body.improvement,
        body.override_reason,
    )

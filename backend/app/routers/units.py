import sqlite3

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response

from ..db import db_dep
from ..deps import current_user
from ..schemas import ScanIn, TestFieldIn, TestFieldUpdate, UnitBulkIn, UnitResultIn
from ..services import attachments as attachments_svc
from ..services import inspection_fields as fields_svc
from ..services import shipments as ship_svc
from ..services import units as units_svc

router = APIRouter(prefix="/api", tags=["Unit inspection"])


@router.post(
    "/units/scan", summary="Look up a unit from the text of its QR code (any shipment you may see)"
)
def scan(
    body: ScanIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return units_svc.get_unit(conn, user, body.code)


@router.get("/units/{code}", summary="A unit's full record: checks, test fields, photos, history")
def get_unit(
    code: str,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return units_svc.get_unit(conn, user, code)


@router.get("/shipments/{shipment_id}/units", summary="The units of a shipment (paged, filterable)")
def list_units(
    shipment_id: int,
    status: str | None = None,
    item_code: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return units_svc.list_units(conn, user, shipment_id, status, item_code, q, limit, offset)


@router.get("/shipments/{shipment_id}/labels", summary="QR label data for the supplier to print")
def labels(
    shipment_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return units_svc.labels(conn, user, shipment_id)


@router.post(
    "/shipments/{shipment_id}/units/bulk",
    summary="Mark many units OK, or set one test field on many units",
)
def bulk(
    shipment_id: int,
    body: UnitBulkIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return units_svc.bulk(conn, user, shipment_id, body.model_dump())


@router.post(
    "/shipments/{shipment_id}/units/import", summary="Upload test results as CSV (all or nothing)"
)
def import_csv(
    shipment_id: int,
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return units_svc.import_csv(
        conn, user, shipment_id, file.file.read(units_svc.CSV_MAX_BYTES + 1)
    )


@router.get(
    "/shipments/{shipment_id}/units.csv",
    summary="All units as CSV (also the template for importing results)",
)
def export_csv(
    shipment_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    text = units_svc.export_csv(conn, user, shipment_id)
    name = ship_svc._row(conn, shipment_id)["shipment_no"]
    return Response(
        text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{name}-units.csv"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/shipments/{shipment_id}/units/{code}/receive", summary="Inspector scans a unit at arrival"
)
def receive(
    shipment_id: int,
    code: str,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return units_svc.receive(conn, user, shipment_id, code)


@router.post(
    "/shipments/{shipment_id}/units/{code}/unreceive",
    summary="Undo a scan before arrival is confirmed",
)
def unreceive(
    shipment_id: int,
    code: str,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return units_svc.unreceive(conn, user, shipment_id, code)


@router.put(
    "/shipments/{shipment_id}/units/{code}",
    summary="Tag a unit OK or Faulty and record its test fields",
)
def record_result(
    shipment_id: int,
    code: str,
    body: UnitResultIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return units_svc.record_result(conn, user, shipment_id, code, body.model_dump())


@router.post(
    "/shipments/{shipment_id}/units/{code}/photo",
    status_code=201,
    summary="Attach a photo to one unit",
)
def unit_photo(
    shipment_id: int,
    code: str,
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    data = file.file.read(attachments_svc.MAX_BYTES + 1)
    return units_svc.add_photo(
        conn, user, shipment_id, code, file.filename or "photo", data, file.content_type
    )


@router.get(
    "/shipments/{shipment_id}/report",
    summary="The delivery quality report (live while testing, frozen once decided)",
)
def report(
    shipment_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return units_svc.lot_report(conn, user, shipment_id)


@router.get("/shipments/{shipment_id}/fields", summary="Test fields defined for this shipment")
def list_fields(
    shipment_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    units_svc._shipment(conn, user, shipment_id)
    return fields_svc.shipment_fields(conn, shipment_id)


@router.post(
    "/shipments/{shipment_id}/fields",
    status_code=201,
    summary="Inspector adds a test field during inspection",
)
def create_field(
    shipment_id: int,
    body: TestFieldIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return fields_svc.create_field(conn, user, shipment_id, body.model_dump())


@router.patch("/shipments/{shipment_id}/fields/{field_id}")
def update_field(
    shipment_id: int,
    field_id: int,
    body: TestFieldUpdate,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return fields_svc.update_field(
        conn, user, shipment_id, field_id, body.model_dump(exclude_unset=True)
    )


@router.delete(
    "/shipments/{shipment_id}/fields/{field_id}",
    summary="Remove a field nobody has recorded a value for yet",
)
def delete_field(
    shipment_id: int,
    field_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    fields_svc.delete_field(conn, user, shipment_id, field_id)
    return {"deleted": field_id}


@router.get(
    "/inspection-fields/templates", summary="Test fields saved for future deliveries of an item"
)
def templates(
    item_code: str | None = None,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return fields_svc.visible_templates(
        conn, user, item_code
    )  # a buyer's inspector sees only that buyer's


@router.delete("/inspection-fields/templates/{template_id}")
def delete_template(
    template_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    fields_svc.delete_template(conn, user, template_id)
    return {"deleted": template_id}

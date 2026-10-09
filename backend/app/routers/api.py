import sqlite3

from fastapi import APIRouter, Depends, Query

from ..db import db_dep
from ..deps import current_user, require_buyer, require_reader, require_roles
from ..schemas import (
    InventoryCreate,
    InventoryUpdate,
    LoginIn,
    POCreate,
    POUpdate,
    RegisterIn,
    SupplierIn,
    SupplierUpdate,
    TokenOut,
    UserOut,
)
from ..services import auth as auth_svc
from ..services import dashboard as dashboard_svc
from ..services import inventory as inventory_svc
from ..services import notifications as notif_svc
from ..services import purchase_orders as po_svc
from ..services import suppliers as suppliers_svc

auth = APIRouter(prefix="/api/auth", tags=["Auth"])
suppliers = APIRouter(prefix="/api/suppliers", tags=["Suppliers"])
purchase_orders = APIRouter(prefix="/api/purchase-orders", tags=["Purchase Orders"])
inventory = APIRouter(prefix="/api/inventory", tags=["Inventory"])
misc = APIRouter(prefix="/api", tags=["Dashboard & Notifications"])


# ---- Auth ----
@auth.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, conn: sqlite3.Connection = Depends(db_dep, scope="function")):
    return auth_svc.register(conn, body.name, body.email, body.password, body.role)


@auth.post("/login", response_model=TokenOut)
def login(body: LoginIn, conn: sqlite3.Connection = Depends(db_dep, scope="function")):
    return auth_svc.login(conn, body.email, body.password)


@auth.get("/me", response_model=UserOut)
def me(
    user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(db_dep, scope="function")
):
    return auth_svc.with_owner(conn, user)


# ---- Suppliers ----
@suppliers.get("")
def list_suppliers(
    q: str | None = None,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(require_reader),
):
    return suppliers_svc.list_suppliers(conn, q, user)


@suppliers.get("/{supplier_id}")
def get_supplier(
    supplier_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    from ..services.errors import Forbidden

    if user["role"] == "supplier" and user.get("supplier_id") != supplier_id:
        raise Forbidden()
    return suppliers_svc.get_supplier(conn, supplier_id, user)


@suppliers.post("", status_code=201)
def create_supplier(
    body: SupplierIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(require_buyer),
):
    return suppliers_svc.create_supplier(conn, **body.model_dump())


@suppliers.put("/{supplier_id}")
def update_supplier(
    supplier_id: int,
    body: SupplierUpdate,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(require_roles("buyer", "admin", "supplier")),
):
    return suppliers_svc.update_supplier(
        conn, user, supplier_id, body.model_dump(exclude_unset=True)
    )


# ---- Purchase orders ----
@purchase_orders.get("")
def list_pos(
    status: str | None = Query(None),
    q: str | None = None,
    view: str | None = Query(
        None,
        pattern="^to_ship$",
        description="`to_ship`: approved orders with something still to ship",
    ),
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return po_svc.list_pos(conn, user, status, q, view)


@purchase_orders.post("", status_code=201)
def create_po(
    body: POCreate,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(require_buyer),
):
    return po_svc.create_po(
        conn, user, body.supplier_id, [i.model_dump() for i in body.items], body.submit
    )


@purchase_orders.get("/{po_id}")
def get_po(
    po_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return po_svc.get_po(conn, user, po_id)


@purchase_orders.put("/{po_id}")
def update_po(
    po_id: int,
    body: POUpdate,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return po_svc.update_po(conn, user, po_id, body.model_dump(exclude_unset=True))


# ---- Inventory ----
_inventory_owner = require_roles(
    "buyer", "admin", "supplier"
)  # may add, edit and delete their own items


@inventory.get("")
def list_inventory(
    q: str | None = None,
    warehouse: str | None = None,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    # Each buyer and supplier sees only their own items (see services/inventory.py).
    user: dict = Depends(require_roles("buyer", "admin", "inspector", "supplier")),
):
    return inventory_svc.list_items(conn, q, warehouse, user)


@inventory.post("", status_code=201, summary="Add an inventory item")
def create_inventory_item(
    body: InventoryCreate,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(_inventory_owner),
):
    return inventory_svc.create_item(conn, user, body.model_dump())


@inventory.put("/{item_code}", summary="Edit an inventory item")
def update_inventory_item(
    item_code: str,
    body: InventoryUpdate,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(_inventory_owner),
):
    return inventory_svc.update_item(conn, user, item_code, body.model_dump(exclude_unset=True))


@inventory.delete(
    "/{item_code}", summary="Delete an item you created, if no PO or requirement uses it"
)
def delete_inventory_item(
    item_code: str,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(_inventory_owner),
):
    inventory_svc.delete_item(conn, user, item_code)
    return {"deleted": item_code.upper()}


@inventory.get("/{item_code}")
def get_inventory_item(
    item_code: str,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(require_reader),
):
    return inventory_svc.get_item(conn, item_code, user)


# ---- Dashboard & notifications ----
@misc.get("/dashboard")
def dashboard(
    conn: sqlite3.Connection = Depends(db_dep, scope="function"), user: dict = Depends(current_user)
):
    if user["role"] == "supplier":
        return {"role": "supplier", **dashboard_svc.supplier_dashboard(conn, user)}
    if user["role"] == "inspector":
        return {"role": "inspector", **dashboard_svc.inspector_dashboard(conn, user)}
    if user["role"] == "admin":
        from ..services import admin as admin_svc

        return {"role": "admin", **admin_svc.stats(conn)}
    return {"role": "buyer", **dashboard_svc.buyer_dashboard(conn, user)}


@misc.get("/notifications")
def notifications(
    conn: sqlite3.Connection = Depends(db_dep, scope="function"), user: dict = Depends(current_user)
):
    return notif_svc.list_for_user(conn, user)


# ---- Requirements & quotes ----
from ..schemas import (  # noqa: E402
    AwardIn,
    DeadlineIn,
    DeclineIn,
    InviteIn,
    MessageIn,
    QuoteIn,
    RequirementCreate,
)
from ..services import messages as msg_svc  # noqa: E402
from ..services import requirements as req_svc  # noqa: E402

requirements = APIRouter(prefix="/api/requirements", tags=["Requirements & Quotes"])


@requirements.get("")
def list_requirements(
    stage: str | None = None,
    mine: bool = False,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    """Buyers: all requirements. Suppliers: open requirements plus ones they quoted on (`mine=true` for only the latter)."""
    return req_svc.list_requirements(conn, user, stage, mine)


@requirements.post("", status_code=201)
def create_requirement(
    body: RequirementCreate,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(require_buyer),
):
    return req_svc.create_requirement(conn, user, body.model_dump())


@requirements.get("/{req_id}")
def get_requirement(
    req_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return req_svc.get_requirement(conn, user, req_id)


@requirements.put("/{req_id}/quote")
def submit_quote(
    req_id: int,
    body: QuoteIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    """Supplier applies (or updates their quote)."""
    return req_svc.submit_quote(conn, user, req_id, body.model_dump())


@requirements.delete("/{req_id}/quote")
def withdraw_quote(
    req_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return req_svc.withdraw_quote(conn, user, req_id)


@requirements.post("/{req_id}/award")
def award_requirement(
    req_id: int,
    body: AwardIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    """Buyer accepts a quote: creates a Pending PO for that supplier and rejects the other quotes."""
    return req_svc.award(conn, user, req_id, body.quote_id)


@requirements.post("/{req_id}/cancel")
def cancel_requirement(
    req_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return req_svc.cancel(conn, user, req_id)


@requirements.get("/{req_id}/messages", summary="Read a conversation (buyers pass ?supplier_id=)")
def read_messages(
    req_id: int,
    supplier_id: int | None = None,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return msg_svc.list_messages(conn, user, req_id, supplier_id)


@requirements.post(
    "/{req_id}/messages", status_code=201, summary="Send a message in a conversation"
)
def send_message(
    req_id: int,
    body: MessageIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return msg_svc.post_message(conn, user, req_id, body.body, body.supplier_id)


@requirements.post("/{req_id}/decline", summary="Supplier declines to quote")
def decline_requirement(
    req_id: int,
    body: DeclineIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return msg_svc.decline(conn, user, req_id, body.reason)


@requirements.put(
    "/{req_id}/deadline", summary="Set, extend or clear the quote deadline (owner, while Open)"
)
def set_requirement_deadline(
    req_id: int,
    body: DeadlineIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return req_svc.set_deadline(conn, user, req_id, body.quote_deadline)


@requirements.post("/{req_id}/open-to-all")
def open_requirement_to_all(
    req_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    """Make an open requirement visible to every supplier, including future ones."""
    return req_svc.open_to_everyone(conn, user, req_id)


@requirements.post("/{req_id}/invite")
def invite_suppliers(
    req_id: int,
    body: InviteIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    """Invite more suppliers to an open requirement."""
    return req_svc.invite_more(conn, user, req_id, body.supplier_ids)


# ---- Attachments ----
from fastapi import File, Form, UploadFile  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402

from ..services import attachments as attachments_svc  # noqa: E402

files = APIRouter(prefix="/api", tags=["Requirement Attachments"])


@files.post(
    "/requirements/{req_id}/attachments",
    status_code=201,
    summary="Attach a file (max 10 MB, whitelisted types)",
)
def upload_attachment(
    req_id: int,
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    data = file.file.read(attachments_svc.MAX_BYTES + 1)  # never read more than the limit + 1 byte
    return req_svc.add_attachment(
        conn, user, req_id, file.filename or "file", data, file.content_type
    )


@files.get("/attachments/{att_id}/download")
def download_attachment(
    att_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    row, path = req_svc.open_attachment(conn, user, att_id)
    return FileResponse(
        path,
        filename=row["filename"],
        media_type="application/octet-stream",  # never let the browser render an uploaded file
        headers={"X-Content-Type-Options": "nosniff"},
    )


@files.delete("/attachments/{att_id}")
def delete_attachment(
    att_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    req_svc.remove_attachment(conn, user, att_id)
    return {"deleted": att_id}


# ---- Message attachments: a file sent inside a buyer <-> supplier conversation ----
@files.post(
    "/requirements/{req_id}/messages/attachments",
    status_code=201,
    summary="Send a message with a file (max 10 MB, whitelisted types; buyers pass supplier_id)",
)
def send_message_with_file(
    req_id: int,
    file: UploadFile = File(...),
    body: str = Form(""),
    supplier_id: int | None = Form(None),
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    data = file.file.read(attachments_svc.MAX_BYTES + 1)  # never read more than the limit + 1 byte
    return msg_svc.post_message(
        conn,
        user,
        req_id,
        body,
        supplier_id,
        file=(file.filename or "file", data, file.content_type),
    )


@files.get("/message-attachments/{att_id}/download")
def download_message_attachment(
    att_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    row, path = msg_svc.open_attachment(conn, user, att_id)
    return FileResponse(
        path,
        filename=row["filename"],
        media_type="application/octet-stream",  # never let the browser render an uploaded file
        headers={"X-Content-Type-Options": "nosniff"},
    )

import sqlite3

from fastapi import APIRouter, Depends

from ..db import db_dep
from ..deps import require_admin, require_buyer
from ..schemas import AdminUserCreate, AdminUserUpdate, ResetIn
from ..services import admin as admin_svc
from ..services.errors import DomainError

router = APIRouter(prefix="/api/admin", tags=["Admin"])
erp = APIRouter(prefix="/api/erp", tags=["ERP Sync"])


@router.get("/stats")
def stats(
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(require_admin),
):
    return admin_svc.stats(conn)


@router.get("/users")
def users(
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(require_admin),
):
    return admin_svc.list_users(conn)


@router.post("/users", status_code=201)
def create_user(
    body: AdminUserCreate,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(require_admin),
):
    return admin_svc.create_user(conn, user, body.model_dump())


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    body: AdminUserUpdate,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(require_admin),
):
    return admin_svc.update_user(conn, user, user_id, body.model_dump(exclude_unset=True))


@router.post("/reset", summary="Wipe all business data and reseed demo data")
def reset(
    body: ResetIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(require_admin),
):
    if body.confirm != "RESET":
        raise DomainError('Send {"confirm": "RESET"} to confirm')
    admin_svc.reset_data(conn, user)
    return {"status": "reset"}


@erp.post("/sync/{name}", summary="Pull items and suppliers from an ERP (sap or infor)")
def sync(
    name: str,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(require_buyer),
):
    return admin_svc.sync_erp(conn, user, name)

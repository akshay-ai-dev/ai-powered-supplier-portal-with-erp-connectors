import sqlite3

from fastapi import APIRouter, Depends

from ..db import db_dep
from ..deps import current_user
from ..services import mailbox

router = APIRouter(prefix="/api/emails", tags=["Emails"])


@router.get("", summary="Emails addressed to the logged-in user")
def inbox(
    conn: sqlite3.Connection = Depends(db_dep, scope="function"), user: dict = Depends(current_user)
):
    return mailbox.list_inbox(conn, user)


@router.get("/{message_id}", summary="One email (only if addressed to the logged-in user)")
def read_email(
    message_id: str,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return mailbox.get_email(conn, user, message_id)

import sqlite3

from fastapi import APIRouter, Depends

from ..db import db_dep
from ..deps import current_user
from ..schemas import TeamInspectorCreate, TeamInspectorUpdate, TeamMessageIn
from ..services import team as team_svc
from ..services import team_messages as chat_svc

router = APIRouter(prefix="/api/team", tags=["Team"])


@router.get("/chat", summary="Your buyer or your own inspectors to chat with")
def chat_contacts(
    conn: sqlite3.Connection = Depends(db_dep, scope="function"), user: dict = Depends(current_user)
):
    return chat_svc.list_contacts(conn, user)


@router.get("/{inspector_id}/messages", summary="Read your private buyer-inspector conversation")
def read_messages(
    inspector_id: int,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return chat_svc.list_messages(conn, user, inspector_id)


@router.post("/{inspector_id}/messages", status_code=201, summary="Message your buyer or inspector")
def send_message(
    inspector_id: int,
    body: TeamMessageIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return chat_svc.post_message(conn, user, inspector_id, body.body)


@router.get("", summary="The inspectors you created (buyers)")
def list_inspectors(
    conn: sqlite3.Connection = Depends(db_dep, scope="function"), user: dict = Depends(current_user)
):
    return team_svc.list_inspectors(conn, user)


@router.post("", status_code=201, summary="Create an inspector who works on your shipments only")
def create_inspector(
    body: TeamInspectorCreate,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return team_svc.create_inspector(conn, user, body.model_dump())


@router.patch(
    "/{user_id}", summary="Rename, reset the password of, disable or enable one of your inspectors"
)
def update_inspector(
    user_id: int,
    body: TeamInspectorUpdate,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    return team_svc.update_inspector(conn, user, user_id, body.model_dump(exclude_unset=True))

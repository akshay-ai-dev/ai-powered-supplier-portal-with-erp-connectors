import sqlite3

from fastapi import APIRouter, Depends

from ..db import db_dep
from ..deps import current_user, require_admin
from ..schemas import TokenCreate
from ..services import tokens as tokens_svc

router = APIRouter(prefix="/api", tags=["API Tokens (for AI agents)"])


@router.get("/tokens", summary="Your API tokens (never includes the secret)")
def my_tokens(conn: sqlite3.Connection = Depends(db_dep), user: dict = Depends(current_user)):
    return tokens_svc.list_tokens(conn, user)


@router.post("/tokens", status_code=201, summary="Create a token. The secret is returned once and cannot be shown again")
def create_token(body: TokenCreate, conn: sqlite3.Connection = Depends(db_dep), user: dict = Depends(current_user)):
    return tokens_svc.create_token(conn, user, body.name, body.scope, body.expires_in_days)


@router.delete("/tokens/{token_id}", summary="Revoke a token (yours, or any token if you are an admin)")
def revoke_token(token_id: int, conn: sqlite3.Connection = Depends(db_dep), user: dict = Depends(current_user)):
    return tokens_svc.revoke(conn, user, token_id)


@router.get("/admin/tokens", summary="Every user's tokens")
def all_tokens(conn: sqlite3.Connection = Depends(db_dep), user: dict = Depends(require_admin)):
    return tokens_svc.list_tokens(conn, user, everyone=True)

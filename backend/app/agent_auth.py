"""Authentication for AI agents: the MCP server and the /api/mcp/* OpenAPI tool endpoints.

Accepted credentials, in order of preference:
  1. a per-user API token (erp_...): acts as its owner, limited to the token's scope
  2. a buyer/admin login JWT: acts as that user (short-lived)
  3. the optional shared MCP_API_KEY: acts as the "MCP Service" buyer (legacy; prefer tokens)
Normal REST endpoints never accept API tokens.
"""
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import get_conn
from .security import decode_token
from .services import tokens as tokens_svc
from .services.context import channel as channel_var
from .services.context import scope as scope_var
from .services.context import token_label as label_var

SERVICE_USER_EMAIL = "mcp-service@erp.local"
RATE_LIMIT = int(os.getenv("AGENT_RATE_LIMIT_PER_MIN", "120"))

bearer = HTTPBearer(auto_error=False)
_hits: dict[str, deque] = defaultdict(deque)


@dataclass
class Principal:
    user_id: int | None  # None = the shared-key service user
    scope: str  # read | write
    label: str | None  # token name, shown in the audit log
    key: str  # rate-limit bucket


def resolve(raw: str) -> Principal | None:
    if not raw:
        return None
    shared = os.getenv("MCP_API_KEY", "")
    if shared and raw == shared:
        return Principal(None, "write", "shared MCP key", "shared-key")
    if raw.startswith(tokens_svc.PREFIX):
        with get_conn() as conn:
            found = tokens_svc.authenticate(conn, raw)
        if found is None:
            return None
        user, tok = found
        return Principal(user["id"], tok["scope"], tok["name"], f"token:{tok['id']}")
    try:
        payload = decode_token(raw)
        uid = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    with get_conn() as conn:
        row = conn.execute("SELECT role, active FROM users WHERE id = ?", (uid,)).fetchone()
    if row is None or not row["active"] or row["role"] not in tokens_svc.AGENT_ROLES:
        return None
    return Principal(uid, "write", None, f"user:{uid}")


def rate_limited(key: str) -> bool:
    """Sliding one-minute window per credential."""
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        return True
    q.append(now)
    return False


def _user_row(user_id: int | None) -> dict:
    with get_conn() as conn:
        row = (
            conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if user_id
            else conn.execute("SELECT * FROM users WHERE email = ?", (SERVICE_USER_EMAIL,)).fetchone()
        )
    if row is None:
        raise HTTPException(401, "Agent user is not provisioned")
    return dict(row)


async def agent_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    """FastAPI dependency for /api/mcp/*. Async on purpose: the context values must be set in the request task
    so the sync endpoint threads (which copy the context) see them."""
    principal = resolve(creds.credentials if creds else "")
    if principal is None:
        raise HTTPException(401, "Provide a buyer API token (erp_...) or a buyer login token")
    if rate_limited(principal.key):
        raise HTTPException(429, f"Too many requests. Limit is {RATE_LIMIT} per minute.")
    channel_var.set("agent-api")
    scope_var.set(principal.scope)
    label_var.set(principal.label)
    return _user_row(principal.user_id)

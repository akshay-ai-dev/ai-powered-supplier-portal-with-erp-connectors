import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import agent_auth
from ..ai import engine, fill, llm
from ..db import db_dep
from ..deps import current_user
from ..services.errors import DomainError

router = APIRouter(prefix="/api/assistant", tags=["Assistant"])


class StepIn(BaseModel):
    state: dict | None = Field(
        default=None,
        description="The state returned by the previous turn; null starts at the menu",
    )
    input: str | None = Field(
        default=None,
        max_length=2100,
        description="What the user typed or the number of the option they pressed",
    )
    tz_offset: int = Field(
        default=0,
        ge=-840,
        le=840,
        description="Browser time-zone offset in minutes (JavaScript getTimezoneOffset)",
    )


class FillIn(StepIn):
    form: str | None = Field(
        default=None,
        description="Start directly on this form (when the user is already on its page)",
    )
    target: int | None = Field(
        default=None,
        description="Requirement id (submit_quote) or purchase order id (ship_order) when already known",
    )


def _limit(user: dict) -> None:
    """Same sliding one-minute window as the agent endpoints, one bucket per user."""
    if agent_auth.rate_limited(f"assistant:{user['id']}"):
        raise HTTPException(429, f"Too many requests. Limit is {agent_auth.RATE_LIMIT} per minute.")


@router.get("/menu", summary="The forms the assistant can fill for your role")
def menu(user: dict = Depends(current_user)):
    # natural-language filling only helps roles that have fill-able forms (inspectors have none)
    return {**engine.menu(user), "ai": llm.get_llm() is not None and bool(fill.forms_for(user))}


@router.post(
    "/step",
    summary="One turn of the guided numbered-menu conversation (stateless: send the state back each time)",
)
def step(
    body: StepIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    _limit(user)
    result = engine.advance(conn, user, body.state, body.input, body.tz_offset)
    if result["stage"] == "menu":
        # tells the widget whether to offer natural-language filling
        result["ai"] = llm.get_llm() is not None and bool(fill.forms_for(user))
    return result


@router.post(
    "/fill",
    summary="One turn of natural-language form filling. Never saves: it returns values for the user to review in the real form",
)
def fill_turn(
    body: FillIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    _limit(user)
    model = llm.get_llm()
    if model is None:
        raise DomainError(
            "The AI assistant is not configured (no OPENAI_API_KEY). Use the numbered menus instead.",
            503,
        )
    return fill.advance(
        conn, user, body.state, body.input, body.tz_offset, model, body.form, body.target
    )

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import agent_auth
from ..ai import chat, engine
from ..db import db_dep
from ..deps import current_user

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


class ChatTurn(BaseModel):
    role: str = Field(description="user (a question) or assistant (a tool call)")
    content: str = Field(default="", max_length=2000, description="The question (user turns)")
    tool: str | None = Field(default=None, description="The tool called (assistant turns)")
    args: dict | None = Field(default=None, description="Its arguments (assistant turns)")


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    history: list[ChatTurn] = Field(
        default_factory=list,
        max_length=20,
        description="Earlier turns of this chat session: the user's questions and the tools called with their arguments",
    )
    tz_offset: int = Field(default=0, ge=-840, le=840)


def _limit(user: dict) -> None:
    """Same sliding one-minute window as the agent endpoints, one bucket per user."""
    if agent_auth.rate_limited(f"assistant:{user['id']}"):
        raise HTTPException(429, f"Too many requests. Limit is {agent_auth.RATE_LIMIT} per minute.")


@router.get("/menu", summary="The forms the assistant can fill for your role")
def menu(user: dict = Depends(current_user)):
    return engine.menu(user)


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
    return engine.advance(conn, user, body.state, body.input, body.tz_offset)


@router.post(
    "/chat",
    summary="Ask in your own words: GPT-4o picks one MCP tool for your role and the tool's result is returned as is",
)
async def ask(
    body: ChatIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(current_user),
):
    _limit(user)
    try:
        return await chat.answer(
            conn, user, body.message, [t.model_dump() for t in body.history], body.tz_offset
        )
    except chat.AssistantUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc

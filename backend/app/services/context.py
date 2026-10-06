"""Request-scoped context describing how an action entered the system.

channel  web        - the browser UI / normal REST calls
         mcp        - an AI agent through the FastMCP server
         agent-api  - an AI agent through the OpenAPI tool endpoints (/api/mcp/*)
         assistant  - the built-in in-app assistant (app/ai/engine.py sets it while submitting a confirmed flow)
scope    read | write - what an agent token may do (write = read + create Drafts); web sessions are always "write"
token_label  name of the API token an agent used, so the audit log can say which one acted
"""

import contextvars

from .errors import Forbidden

channel: contextvars.ContextVar[str] = contextvars.ContextVar("channel", default="web")
scope: contextvars.ContextVar[str] = contextvars.ContextVar("scope", default="write")
token_label: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "token_label", default=None
)

AGENT_CHANNELS = {"mcp", "agent-api", "assistant"}


def current_channel() -> str:
    return channel.get()


def require_write() -> None:
    if scope.get() != "write":
        raise Forbidden(
            "This API token is read-only. Create a token with the 'write' scope to let an agent create drafts."
        )

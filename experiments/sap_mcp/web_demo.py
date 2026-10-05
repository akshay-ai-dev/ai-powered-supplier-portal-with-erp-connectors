"""Local web page to demo the SAP MCP server: http://localhost:8765

The browser never talks to SAP. Each click goes:
  browser -> this page's /api/call -> MCP client -> mcp_server.py (MCP over stdio) -> SAP OData API
and the page shows the clean tool result plus the real SAP calls (URL, HTTP status, time).

Run from the repo root (same throwaway container as script.py, plus a port):
    docker run --rm -p 8765:8765 -v "$PWD":/repo -w /repo/experiments/sap_mcp python:3.12-slim \
      sh -c "pip install -q --root-user-action=ignore 'mcp==2.2.0' httpx google-genai anthropic && python web_demo.py"
Only the Python standard library is used for the web part; the page itself is web_demo.html.
The "AI assistant" tab (ai_agent.py) needs GEMINI_API_KEY or ANTHROPIC_API_KEY in .env (AI_PROVIDER picks one).
"""

import asyncio
import json
import os
import re
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sap_client  # noqa: E402  (reads .env, gives the mode)

PORT = int(os.environ.get("SAP_DEMO_PORT") or 8765)
SERVER = StdioServerParameters(command=sys.executable, args=[str(HERE / "mcp_server.py")], env=dict(os.environ))


async def mcp_call(tool: str | None, args: dict) -> dict:
    """Start the MCP server, list its tools, optionally call one. Returns result + SAP log lines."""
    with tempfile.TemporaryFile("w+") as errlog:
        started = time.perf_counter()
        async with stdio_client(SERVER, errlog=errlog) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            listed = (await session.list_tools()).tools
            tools = [{"name": t.name, "description": (t.description or "").strip(), "inputSchema": t.input_schema}
                     for t in listed]
            result = None
            if tool:
                match = next((t for t in listed if t.name == tool), None)
                if match is None:
                    raise ValueError(f"Unknown tool '{tool}'. Available: {', '.join(t.name for t in listed)}")
                args = coerce_args(args, match.input_schema)
                raw = await session.call_tool(tool, args)
                data = getattr(raw, "structured_content", None) or json.loads(raw.content[0].text)
                result = data.get("result", data) if isinstance(data, dict) else data
        elapsed = (time.perf_counter() - started) * 1000
        errlog.seek(0)
        log = [line.rstrip() for line in errlog if line.startswith("[sap]")]
    return {"tools": tools, "result": result, "sapLog": log, "sapCalls": parse_calls(log), "elapsedMs": round(elapsed)}


def coerce_args(args: dict, schema: dict) -> dict:
    """Form values arrive as text; convert them to the types in the tool's input schema."""
    out = {}
    for key, value in args.items():
        prop = (schema.get("properties") or {}).get(key, {})
        kinds = {p.get("type") for p in prop.get("anyOf", [prop])}
        try:
            if "integer" in kinds:
                value = int(value)
            elif "number" in kinds:
                value = float(value)
            elif "boolean" in kinds and isinstance(value, str):
                value = value.lower() in ("true", "1", "yes")
        except (TypeError, ValueError):
            pass  # leave as text; the MCP server validates and returns a clear error
        out[key] = value
    return out


def parse_calls(log: list[str]) -> list[dict]:
    """Turn the server's [sap] log lines into rows: endpoint, HTTP status, time."""
    calls: list[dict] = []
    for line in log:
        text = line[len("[sap]") :].strip()
        if text.startswith("GET"):
            url = text[3:].strip().split(" {", 1)[0]
            calls.append({"method": "GET", "url": url, "endpoint": url.split("/sap/opu/odata/sap/")[-1], "status": None})
        elif text.startswith("SAP") and calls:
            parts = text.split()  # SAP HTTP 200 in 668 ms
            calls[-1]["status"] = int(parts[2]) if parts[2].isdigit() else parts[2]
            calls[-1]["ms"] = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else None
        elif text.startswith("mock"):
            calls.append({"method": "GET", "url": "", "endpoint": text[4:].strip(), "status": "mock", "ms": 0})
    return calls


def root_error(exc: BaseException) -> str:
    """asyncio/anyio wrap failures in ExceptionGroup; show the real cause (and log the traceback)."""
    import traceback

    traceback.print_exception(exc, file=sys.stderr)
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return f"{exc.__class__.__name__}: {exc}"[:800]


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data, indent=2).encode(), "application/json")

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.replace("__MODE__", sap_client.MODE).encode(), "text/html; charset=utf-8")
        elif self.path == "/api/config":
            import ai_agent  # imported here: it imports this module

            info = {k: v for k, v in ai_agent.provider_info().items() if not k.startswith("_")}  # never send the key
            self._json(200, {"sapMode": sap_client.MODE, "ai": info})
        elif self.path == "/api/tools":
            self._json(200, asyncio.run(mcp_call(None, {})))
        else:
            self._send(404, b"Not found", "text/plain")

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/api/chat":
            import ai_agent

            question = str(body.get("question") or "").strip()[:2000]
            if not question:
                return self._json(400, {"error": "empty question"})
            try:
                return self._json(200, asyncio.run(ai_agent.ask(question, body.get("history") or [])))
            except Exception as exc:
                return self._json(500, {"error": root_error(exc)})
        if self.path != "/api/call":
            return self._send(404, b"Not found", "text/plain")
        tool, args = str(body.get("tool") or ""), body.get("args") or {}
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", tool):
            return self._json(400, {"error": "invalid tool name"})
        args = {k: v for k, v in args.items() if v not in ("", None)}  # empty field = use the tool's default
        try:
            self._json(200, {"tool": tool, "args": args, **asyncio.run(mcp_call(tool, args))})
        except Exception as exc:  # show the error on the page instead of a blank screen
            self._json(500, {"error": root_error(exc)})

    def log_message(self, fmt: str, *args) -> None:
        print(f"[web] {self.command} {self.path}", file=sys.stderr)


PAGE = (HERE / "web_demo.html").read_text(encoding="utf-8")


if __name__ == "__main__":
    print(f"SAP MCP demo on http://localhost:{PORT}  (SAP_MODE={sap_client.MODE}). Ctrl+C to stop.", file=sys.stderr)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

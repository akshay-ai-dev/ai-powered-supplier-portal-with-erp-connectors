"""Proof script: talk to the SAP MCP server exactly like an AI client would.

It starts mcp_server.py over stdio (the real MCP protocol), lists the tools,
calls each one, and runs a few safety checks.

Run from the repo root:
    uv run --directory backend python ../experiments/sap_mcp/script.py
or inside Docker:
    docker compose exec api python ../experiments/sap_mcp/script.py

SAP_MODE in .env decides the data source: mock (default), sandbox or real.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sap_client  # noqa: E402  (after sys.path so it is found from any folder)

CALLS = [
    ("search_suppliers", {"top": 3}),
    ("get_supplier", {"supplier_id": "1018"}),
    ("list_purchase_orders", {"top": 3}),
]

CHECKS = [
    # (description, tool, args, expectation on the result)
    (
        "Unknown supplier -> found=false (not invented)",
        "get_supplier",
        {"supplier_id": "9999999"},
        lambda r: r.get("found") is False and "error" not in r,
    ),
    (
        "Injection attempt rejected",
        "get_supplier",
        {"supplier_id": "1018') or 1 eq 1 or ('"},
        lambda r: r.get("found") is False and "must be" in r.get("error", ""),
    ),
    ("top is capped at 20", "search_suppliers", {"top": 500}, lambda r: r.get("found") and r["count"] <= 20),
]


def _result(call_result) -> dict:
    if getattr(call_result, "structuredContent", None):
        data = call_result.structuredContent
        return data.get("result", data) if isinstance(data, dict) else data
    return json.loads(call_result.content[0].text)


async def main() -> int:
    print(f"SAP_MODE = {sap_client.MODE}\n")
    # Pass the environment on, so the server uses the same SAP_MODE and key as this script.
    server = StdioServerParameters(command=sys.executable, args=[str(HERE / "mcp_server.py")], env=dict(os.environ))
    async with stdio_client(server) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        tools = await session.list_tools()
        names = [t.name for t in tools.tools]
        print(f"MCP tools available ({len(names)}): {', '.join(names)}\n")

        for name, args in CALLS:
            result = _result(await session.call_tool(name, args))
            print(f"--- {name}({json.dumps(args)}) ---")
            print(json.dumps(result, indent=2))
            print()

        print("--- Safety checks ---")
        passed = 0
        for label, name, args, ok in CHECKS:
            good = ok(_result(await session.call_tool(name, args)))
            passed += good
            print(f"{'PASS' if good else 'FAIL'}  {label}")
        print(f"\n{passed}/{len(CHECKS)} checks passed")
        return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

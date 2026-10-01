"""Smoke-test the ERP Copilot MCP server the way an AI agent would.

    python scripts/mcp_check.py --token <buyer JWT or MCP_API_KEY>
    python scripts/mcp_check.py --email buyer@demo.com --password 'Password123!'

Steps: connect -> list tools -> call read-only tools. Pass --write to also create a Draft PO (flagged as an AI action).
Exit code is non-zero if anything fails, so it can be used in CI.
"""
import argparse
import asyncio
import json
import sys
import urllib.request

from fastmcp import Client


def login(base: str, email: str, password: str) -> str:
    req = urllib.request.Request(
        f"{base}/api/auth/login",
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)["access_token"]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000", help="API base URL")
    ap.add_argument("--token", help="buyer JWT or the static MCP_API_KEY")
    ap.add_argument("--email")
    ap.add_argument("--password")
    ap.add_argument("--write", action="store_true", help="also create a Draft purchase order")
    args = ap.parse_args()

    token = args.token or (login(args.base, args.email, args.password) if args.email else None)
    if not token:
        print("Provide --token, or --email and --password")
        return 2

    failures = 0

    def ok(label, detail=""):
        print(f"  OK    {label} {detail}")

    def bad(label, err):
        nonlocal failures
        failures += 1
        print(f"  FAIL  {label}: {err}")

    async with Client(f"{args.base}/mcp/", auth=token) as c:
        tools = await c.list_tools()
        print(f"Connected. {len(tools)} tools:")
        for t in tools:
            print(f"   - {t.name}: {(t.description or '').splitlines()[0]}")
        names = {t.name for t in tools}

        checks = [
            ("get_inventory", {"item_code": "ITEM001"}),
            ("search_supplier", {"supplier_name": "a"}),
            ("list_requirements", {}),
            ("list_purchase_orders", {}),
        ]
        for name, params in checks:
            if name not in names:
                bad(name, "tool not offered")
                continue
            try:
                r = await c.call_tool(name, params)
                data = r.data
                ok(name, f"-> {len(data)} item(s)" if isinstance(data, list) else f"-> {json.dumps(data)[:80]}")
            except Exception as exc:  # noqa: BLE001
                bad(name, exc)

        try:
            await c.call_tool("get_inventory", {"item_code": "NO-SUCH-ITEM"})
            bad("error handling", "expected a tool error for an unknown item")
        except Exception as exc:  # noqa: BLE001
            ok("error handling", f"-> {str(exc)[:60]}")

        if args.write:
            try:
                sup = (await c.call_tool("search_supplier", {"supplier_name": ""})).data[0]["id"]
                r = await c.call_tool("create_purchase_order", {"supplier_id": sup, "item_code": "ITEM001", "quantity": 1})
                ok("create_purchase_order", f"-> {r.data['po_number']} (created_via={r.data['created_via']})")
            except Exception as exc:  # noqa: BLE001
                bad("create_purchase_order", exc)

    print("PASSED" if not failures else f"{failures} check(s) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

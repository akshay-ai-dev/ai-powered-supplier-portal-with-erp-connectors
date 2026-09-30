"""Local AI demo entry point. Run: uv run python script.py <check|ask|chat|test|prefill|serve>."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="SRS supplier portal – AI experiment")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Offline checks of the MCP tools (no API key needed)")
    p_ask = sub.add_parser("ask", help="Ask the buyer assistant one question")
    p_ask.add_argument("prompt")
    sub.add_parser("chat", help="Interactive chat with the buyer assistant")
    sub.add_parser("test", help="Run the 10 fixed test prompts through OpenAI")
    p_pre = sub.add_parser("prefill", help="Pre-fill a shipment form from a packing list")
    p_pre.add_argument("file")
    p_pre.add_argument("--po-qty", type=int, default=None,
                       help="PO quantity typed in by hand as sample input (not read from an ERP)")
    sub.add_parser("serve", help="Run the MCP server over stdio")
    args = parser.parse_args()

    # stderr, so `serve` keeps stdout clean for the MCP stdio protocol
    print(
        f"Model: {settings.OPENAI_MODEL}   API key set: {settings.has_real_key()}\n",
        file=sys.stderr,
    )

    if args.command == "check":
        import unittest

        from test_prompts import offline_checks

        ok = asyncio.run(offline_checks())
        print("\n  Award eligibility, assistant grounding, ranking and pre-fill tests")
        suite = unittest.defaultTestLoader.loadTestsFromNames(
            ["test_award", "test_grounding", "test_accuracy", "test_portal_data"])
        ok = unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() and ok
        sys.exit(0 if ok else 1)

    if args.command == "test":
        from test_prompts import live_tests

        sys.exit(0 if asyncio.run(live_tests()) else 1)

    if args.command == "ask":
        from assistant import ask, show_draft

        out = asyncio.run(ask(args.prompt))
        print(f"\n{out['answer']}")
        for d in out["drafts"]:
            show_draft(d)
        return

    if args.command == "chat":
        from assistant import ask, show_draft

        history: list = []
        print("Buyer assistant. Type 'exit' to quit.")
        while True:
            try:
                prompt = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if prompt.lower() in ("exit", "quit"):
                break
            if not prompt:
                continue
            out = asyncio.run(ask(prompt, history=history))
            history = out["messages"]
            print(f"\nAssistant: {out['answer']}")
            for d in out["drafts"]:
                show_draft(d)
        return

    if args.command == "prefill":
        from prefill import prefill

        result = prefill(args.file, po_quantity=args.po_qty)
        print(json.dumps(result, indent=2))
        if result["manualEntryRequired"]:
            missing = ", ".join(m["label"] for m in result["manualEntryRequired"])
            print(f"\nNeeds manual entry (not readable in the document): {missing}")
        if result["poQuantityNote"]:
            print(f"\n{result['poQuantityNote']}")
        print(f"\nQuantity check: {result['quantityCheck']['message']}")
        print(f"\n{result['note']}")
        return

    if args.command == "serve":
        from mcp_server import mcp

        mcp.run()


if __name__ == "__main__":
    main()

"""AI assistant for the demo console: an LLM answers questions using our SAP MCP tools.

    question -> LLM (Gemini or Claude) -> picks a tool -> MCP client -> mcp_server.py -> SAP
             <- LLM writes the answer   <- tool result <-

The LLM never sees the SAP key or SAP URLs; it only sees the 3 MCP tools.
Provider is chosen in .env, so swapping models needs no code change:

    AI_PROVIDER=gemini   GEMINI_API_KEY=...     GEMINI_MODEL=gemini-3.8-flash   (default model)
                         GEMINI_FALLBACK_MODELS=...  optional; otherwise the key's available flash models are used
    AI_PROVIDER=claude   ANTHROPIC_API_KEY=...  CLAUDE_MODEL=claude-sonnet-5-5
"""

import asyncio
import json
import os
import sys
import tempfile
import time

from mcp import ClientSession
from mcp.client.stdio import stdio_client

import sap_client  # noqa: F401  (loads .env)
from web_demo import SERVER, parse_calls

MAX_ROUNDS = 6  # stop a runaway tool loop
SYSTEM = (
    "You are the procurement assistant of the SRS Supplier Portal. You can read SAP S/4HANA data only through "
    "the provided tools: dedicated tools for suppliers and purchase orders, plus list_sap_apis / query_sap for other SAP APIs (purchase requisitions, PO items, goods receipts, products, supplier invoices). Prefer the dedicated tools when they fit; for query_sap use SAP field names and keep top small. Rules: answer only from tool results; never invent IDs, "
    "names, dates or numbers; if a tool returns found=false or an error, say so plainly; you cannot create or change "
    "anything in SAP. Use as few tool calls as possible (usually one); do not repeat a call that already returned the data you need. Keep answers short. Use a markdown table for lists. Mention that data comes from SAP."
)


def provider_info() -> dict:
    provider = (os.environ.get("AI_PROVIDER") or "gemini").strip().lower()
    if provider == "claude":
        key, model = os.environ.get("ANTHROPIC_API_KEY", ""), os.environ.get("CLAUDE_MODEL") or "claude-sonnet-5-5"
    else:
        provider = "gemini"
        key, model = os.environ.get("GEMINI_API_KEY", ""), os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"
    key = key.strip()
    ok = bool(key) and "replace" not in key and "paste" not in key
    return {"provider": provider, "model": model.strip(), "keyConfigured": ok, "_key": key}


def _clean_schema(schema: dict) -> dict:
    """MCP (pydantic) schemas use anyOf[..., null] and titles; keep a plain JSON schema every model accepts."""
    props = {}
    for name, prop in (schema.get("properties") or {}).items():
        if "anyOf" in prop:
            kinds = [p for p in prop["anyOf"] if p.get("type") != "null"]
            prop = {**(kinds[0] if kinds else {"type": "string"}), **{k: v for k, v in prop.items() if k != "anyOf"}}
        props[name] = {k: v for k, v in prop.items() if k in ("type", "description", "enum")}
    return {"type": "object", "properties": props, "required": schema.get("required", [])}


async def ask(question: str, history: list[dict]) -> dict:
    info = provider_info()
    if not info["keyConfigured"]:
        var = "ANTHROPIC_API_KEY" if info["provider"] == "claude" else "GEMINI_API_KEY"
        raise RuntimeError(f"No API key: add {var}=... to .env and restart the console.")

    steps: list[dict] = []
    started = time.perf_counter()
    with tempfile.TemporaryFile("w+") as errlog:
        async with stdio_client(SERVER, errlog=errlog) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools

            async def run_tool(name: str, args: dict) -> dict:
                errlog.seek(0, 2)
                mark = errlog.tell()
                t0 = time.perf_counter()
                raw = await session.call_tool(name, args)
                data = getattr(raw, "structured_content", None) or json.loads(raw.content[0].text)
                data = data.get("result", data) if isinstance(data, dict) else data
                errlog.flush()
                errlog.seek(mark)
                lines = [ln.rstrip() for ln in errlog if ln.startswith("[sap]")]
                steps.append({"tool": name, "args": args, "result": data, "sapCalls": parse_calls(lines),
                              "ms": round((time.perf_counter() - t0) * 1000)})
                return data

            if info["provider"] == "claude":
                answer, usage = await _ask_claude(info, tools, question, history, run_tool)
            else:
                answer, usage = await _ask_gemini(info, tools, question, history, run_tool)

    return {"answer": answer, "steps": steps, "provider": info["provider"], "model": info.get("usedModel", info["model"]),
            "usage": usage, "elapsedMs": round((time.perf_counter() - started) * 1000)}


RETRY_CODES = {429, 500, 503, 504}  # busy / quota / temporary errors


_DISCOVERED: list[str] = []


async def _available_flash_models(client) -> list[str]:
    """Ask Google which models this API key can use (cached), newest 'flash' models first."""
    if not _DISCOVERED:
        try:
            pager = await client.aio.models.list()
            async for m in pager:
                name = (m.name or "").removeprefix("models/")
                if "flash" in name and "generateContent" in (m.supported_actions or []) and "image" not in name \
                        and "tts" not in name and "audio" not in name:
                    _DISCOVERED.append(name)
        except Exception as exc:  # listing is a nice-to-have
            print(f"[ai] could not list models: {exc}", file=sys.stderr)
        _DISCOVERED.sort(reverse=True)
    return _DISCOVERED


async def _gemini_generate(client, info, contents, config):
    """Call Gemini. Busy (503) or quota (429): wait and retry. Retired model (404): try the next one.
    Fallbacks: GEMINI_FALLBACK_MODELS, then the flash models Google says this key can use."""
    from google.genai import errors

    configured = [m.strip() for m in (os.environ.get("GEMINI_FALLBACK_MODELS") or "").split(",") if m.strip()]
    tried, busy = set(), None
    candidates = [info["model"], *configured]
    i = 0
    while i < len(candidates):
        model = candidates[i]
        i += 1
        if model in tried:
            continue
        tried.add(model)
        for attempt in range(3):
            try:
                resp = await client.aio.models.generate_content(model=model, contents=contents, config=config)
                if model != info["model"]:
                    info["usedModel"] = model
                return resp
            except errors.APIError as exc:
                if exc.code == 404:  # model retired / not available for this key
                    print(f"[ai] {model} not available (404), trying another model", file=sys.stderr)
                    break
                if exc.code not in RETRY_CODES:
                    raise
                busy = exc
                print(f"[ai] {model} busy ({exc.code}), retry {attempt + 1}/3", file=sys.stderr)
                await asyncio.sleep(2 ** (attempt + 1))  # 2 s, 4 s, 8 s
        if i == len(candidates):  # out of configured models: add what Google says is available
            candidates += [m for m in await _available_flash_models(client) if m not in tried][:3]
    if busy:
        raise RuntimeError("Gemini is overloaded right now (503/429 on every available model). "
                           "Please try again in a minute.") from busy
    raise RuntimeError("No Gemini model available for this API key. Check GEMINI_MODEL in .env.")


async def _ask_gemini(info, tools, question, history, run_tool):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=info["_key"])
    decls = [types.FunctionDeclaration(name=t.name, description=(t.description or "").strip(),
                                       parameters_json_schema=_clean_schema(t.input_schema)) for t in tools]
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        tools=[types.Tool(function_declarations=decls)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = [types.Content(role="user" if m["role"] == "user" else "model", parts=[types.Part(text=m["text"])])
                for m in history if m.get("text")]
    contents.append(types.Content(role="user", parts=[types.Part(text=question)]))
    usage = {"input": 0, "output": 0}

    for _ in range(MAX_ROUNDS):
        resp = await _gemini_generate(client, info, contents, config)
        meta = resp.usage_metadata
        if meta:
            usage["input"] += meta.prompt_token_count or 0
            usage["output"] += meta.candidates_token_count or 0
        content = resp.candidates[0].content if resp.candidates else None
        calls = [p.function_call for p in (content.parts if content and content.parts else []) if p.function_call]
        if not calls:
            return (resp.text or "(no answer)").strip(), usage
        contents.append(content)
        replies = []
        for call in calls:
            data = await run_tool(call.name, dict(call.args or {}))
            replies.append(types.Part.from_function_response(name=call.name, response={"result": data}))
        contents.append(types.Content(role="user", parts=replies))
    return "Stopped: too many tool calls for one question.", usage


async def _ask_claude(info, tools, question, history, run_tool):
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=info["_key"])
    tool_defs = [{"name": t.name, "description": (t.description or "").strip(),
                  "input_schema": _clean_schema(t.input_schema)} for t in tools]
    messages = [{"role": "user" if m["role"] == "user" else "assistant", "content": m["text"]}
                for m in history if m.get("text")]
    messages.append({"role": "user", "content": question})
    usage = {"input": 0, "output": 0}

    for _ in range(MAX_ROUNDS):
        resp = await client.messages.create(model=info["model"], max_tokens=1500, system=SYSTEM,
                                            tools=tool_defs, messages=messages)
        usage["input"] += resp.usage.input_tokens
        usage["output"] += resp.usage.output_tokens
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text").strip() or "(no answer)", usage
        messages.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content]})
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                data = await run_tool(block.name, dict(block.input or {}))
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(data)})
        messages.append({"role": "user", "content": results})
    return "Stopped: too many tool calls for one question.", usage


if __name__ == "__main__":  # quick CLI test: python ai_agent.py "show me 3 suppliers"
    import asyncio

    out = asyncio.run(ask(" ".join(sys.argv[1:]) or "Show me 3 suppliers.", []))
    print(json.dumps(out, indent=2))

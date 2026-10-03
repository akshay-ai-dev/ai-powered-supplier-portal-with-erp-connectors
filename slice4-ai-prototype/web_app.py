"""Local, read-only AI demo. Run: uv run uvicorn web_app:app --host 127.0.0.1 --port 8008"""
import json
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import settings
from assistant import ask
from mcp_server import mcp
from portal_data import SampleData, portal_data
from prefill import prefill_bytes

app = FastAPI(title="SRS AI Slice 4 Demo")
HERE = Path(__file__).resolve().parent
FRONTEND_DIST = HERE / "frontend" / "dist"
if (FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1000)
    history: list[dict] = Field(default_factory=list)


class AwardRequest(BaseModel):
    request_id: str
    supplier_id: str | None = None
    justification: str = ""


@app.get("/")
def index():
    page = FRONTEND_DIST / "index.html"
    if not page.is_file():
        raise HTTPException(503, "React frontend not built. Run npm install and npm run build in frontend/.")
    return FileResponse(page)


async def tool(name: str, args: dict) -> dict:
    result = await mcp.call_tool(name, args)
    return json.loads("".join(getattr(c, "text", "") for c in result.content))


@app.get("/api/status")
def status():
    sample = isinstance(portal_data(), SampleData)
    return {"mode": "sample data" if sample else "portal data",
            "dataSource": type(portal_data()).__name__, "liveAIReady": settings.has_real_key(),
            "model": settings.OPENAI_MODEL, "erpWriteEnabled": False}


@app.get("/api/requests")
async def requests():
    return await tool("list_requests", {})


@app.get("/api/requests/{request_id}")
async def detail(request_id: str):
    return await tool("get_request_detail", {"record_id": request_id})


@app.get("/api/requests/{request_id}/comparison")
async def comparison(request_id: str):
    return await tool("compare_responses", {"request_id": request_id})


@app.post("/api/draft-award")
async def draft_award(payload: AwardRequest):
    return await tool("draft_award", payload.model_dump(exclude_none=True))


@app.post("/api/chat")
async def chat(payload: ChatRequest):
    if not settings.has_real_key():
        raise HTTPException(503, "OPENAI_API_KEY is not set; sample comparison is available.")
    try:
        result = await ask(payload.prompt, history=payload.history)
        return {"answer": result["answer"], "trace": result["trace"],
                "drafts": result["drafts"], "messages": result["messages"],
                "grounding": result["grounding"]}
    except Exception as exc:
        raise HTTPException(502, f"OpenAI request failed: {exc.__class__.__name__}: {exc}") from exc


@app.post("/api/prefill")
async def prefill(file: UploadFile = File(...), po_quantity: int | None = Form(None)):
    if not settings.has_real_key():
        raise HTTPException(503, "OPENAI_API_KEY is not set; document extraction needs AI.")
    data = await file.read(8 * 1024 * 1024 + 1)
    try:
        return prefill_bytes(data, file.filename or "file", po_quantity)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Document extraction failed: {exc.__class__.__name__}: {exc}") from exc

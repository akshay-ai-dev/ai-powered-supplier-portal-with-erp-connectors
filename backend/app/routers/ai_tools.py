"""OpenAPI-compatible REST surface for the same tools the MCP server exposes.
Agents that speak OpenAPI (rather than MCP) can import /openapi.json and call these."""

import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..agent_auth import agent_user
from ..db import db_dep
from ..mcp_server import mcp
from ..services import agent_tools
from ..services.context import require_write

router = APIRouter(prefix="/api/mcp", tags=["MCP Tools (OpenAPI)"])


class InventoryIn(BaseModel):
    item_code: str = Field(examples=["ITEM001"])


class SupplierSearchIn(BaseModel):
    supplier_name: str = Field(examples=["ABC"])


class CreatePOIn(BaseModel):
    supplier_id: int = Field(examples=[1])
    item_code: str = Field(examples=["ITEM001"])
    quantity: int = Field(gt=0, examples=[100])
    unit_price: float | None = Field(default=None, ge=0)


class GetPOIn(BaseModel):
    po_number: str = Field(examples=["PO1001"])


class ListPOsIn(BaseModel):
    status: str | None = Field(default=None, examples=["Approved"])


class ListRequestsIn(BaseModel):
    status: str | None = Field(default=None, examples=["Quoted"])


class ReqNumberIn(BaseModel):
    req_number: str = Field(examples=["REQ2001"])


@router.get("/tools", summary="Tool discovery")
async def discover_tools():
    tools = await mcp.list_tools()
    return [
        {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
    ]


@router.post("/get_inventory", operation_id="get_inventory")
def get_inventory(
    body: InventoryIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(agent_user),
):
    return agent_tools.get_inventory(conn, body.item_code, user)


@router.post("/search_suppliers", operation_id="search_suppliers")
def search_suppliers(
    body: SupplierSearchIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(agent_user),
):
    return agent_tools.search_suppliers(conn, body.supplier_name)


@router.post("/create_purchase_order", operation_id="create_purchase_order", status_code=201)
def create_purchase_order(
    body: CreatePOIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(agent_user),
):
    require_write()  # read-only tokens may look but not create
    return agent_tools.create_purchase_order(
        conn, user, body.supplier_id, body.item_code, body.quantity, body.unit_price
    )


@router.post("/get_purchase_order", operation_id="get_purchase_order")
def get_purchase_order(
    body: GetPOIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(agent_user),
):
    return agent_tools.get_purchase_order(conn, user, body.po_number)


@router.post("/list_purchase_orders", operation_id="list_purchase_orders")
def list_purchase_orders(
    body: ListPOsIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(agent_user),
):
    return agent_tools.list_purchase_orders(conn, user, body.status)


@router.post("/list_requests", operation_id="list_requests")
def list_requests(
    body: ListRequestsIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(agent_user),
):
    return agent_tools.list_requests(conn, user, body.status)


@router.post("/get_request_detail", operation_id="get_request_detail")
def get_request_detail(
    body: ReqNumberIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(agent_user),
):
    return agent_tools.get_request_detail(conn, user, body.req_number)


@router.post("/compare_responses", operation_id="compare_responses")
def compare_responses(
    body: ReqNumberIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(agent_user),
):
    return agent_tools.compare_responses(conn, user, body.req_number)


@router.post("/draft_award", operation_id="draft_award", summary="Propose an award (saves nothing)")
def draft_award(
    body: ReqNumberIn,
    conn: sqlite3.Connection = Depends(db_dep, scope="function"),
    user: dict = Depends(agent_user),
):
    return agent_tools.draft_award(conn, user, body.req_number)

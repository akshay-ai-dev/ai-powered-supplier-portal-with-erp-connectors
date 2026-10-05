"""Custom read-only MCP server for SAP S/4HANA (POC).

SAP has no free MCP server for business data (the official route is the MCP Gateway in
SAP Integration Suite, which needs a BTP licence). This server wraps SAP's standard
OData APIs as business-level tools an AI assistant can call:

    search_suppliers      API_BUSINESS_PARTNER / A_Supplier
    get_supplier          API_BUSINESS_PARTNER / A_Supplier('<id>')
    list_purchase_orders  API_PURCHASEORDER_PROCESS_SRV / A_PurchaseOrder
    list_sap_apis         the allow-list of SAP APIs the generic tool may read
    query_sap             generic read of any allow-listed API (filter / select / orderby / top)

Read-only by design: there is no tool that creates or changes anything in SAP.
Each tool returns a short, clean result (a few useful fields instead of ~50 raw ones).

mcp 2.x: FastMCP was renamed to MCPServer (mcp.server.mcpserver).
Run over stdio:  python mcp_server.py
"""

import re
from typing import Literal

from mcp.server.mcpserver import MCPServer

import sap_client as sap

mcp = MCPServer(
    "sap-s4hana-readonly",
    instructions=(
        "Read-only access to SAP S/4HANA supplier and purchase order data. "
        "Answer only from tool results; if a tool says found=false, say it was not found."
    ),
)


def _fail(message: str) -> dict:
    return {"found": False, "error": message, "source": sap.MODE}


def _supplier(row: dict) -> dict:
    return {
        "supplierId": row.get("Supplier"),
        "name": row.get("SupplierName"),
        "fullName": row.get("SupplierFullName"),
        "createdOn": sap.sap_date(row.get("CreationDate")),
        "purchasingBlocked": bool(row.get("PurchasingIsBlocked")),
        "paymentBlocked": bool(row.get("PaymentIsBlockedForSupplier")),
        "postingBlocked": bool(row.get("PostingIsBlocked")),
        "markedForDeletion": bool(row.get("DeletionIndicator")),
    }


SUPPLIER_FIELDS = (
    "Supplier,SupplierName,SupplierFullName,CreationDate,PurchasingIsBlocked,"
    "PaymentIsBlockedForSupplier,PostingIsBlocked,DeletionIndicator"
)


@mcp.tool()
def search_suppliers(name_contains: str | None = None, top: int = 5) -> dict:
    """Search SAP suppliers, optionally by part of the name (case-sensitive in SAP).

    Returns supplier ID, name, creation date and whether purchasing, payment or
    posting is blocked. `top` is the maximum number of suppliers (1-20).
    """
    top = sap.clamp_top(top)
    params = {"$top": str(top), "$select": SUPPLIER_FIELDS}
    if name_contains:
        params["$filter"] = f"substringof('{sap.odata_text(name_contains)}',SupplierName) eq true"
    try:
        rows = sap.odata_get(sap.SUPPLIER_SERVICE, "A_Supplier", params)
    except sap.SapError as exc:
        return _fail(str(exc))

    if name_contains:  # same result in mock mode, harmless in sandbox/real
        rows = [r for r in rows if name_contains.lower() in (r.get("SupplierName") or "").lower()]
    suppliers = [_supplier(r) for r in rows[:top]]
    return {"found": bool(suppliers), "count": len(suppliers), "suppliers": suppliers, "source": sap.MODE}


@mcp.tool()
def get_supplier(supplier_id: str) -> dict:
    """Get one SAP supplier by its supplier ID (for example "1018")."""
    try:
        supplier_id = sap.check_id(supplier_id, "supplier_id")
        if sap.MODE == "mock":
            rows = [r for r in sap.odata_get(sap.SUPPLIER_SERVICE, "A_Supplier") if r.get("Supplier") == supplier_id]
        else:
            rows = sap.odata_get(sap.SUPPLIER_SERVICE, f"A_Supplier('{supplier_id}')", {"$select": SUPPLIER_FIELDS})
    except ValueError as exc:
        return _fail(str(exc))
    except sap.SapError as exc:
        return _fail(str(exc))

    if not rows:
        return {"found": False, "message": f"No supplier with ID {supplier_id} exists in SAP.", "source": sap.MODE}
    return {"found": True, "supplier": _supplier(rows[0]), "source": sap.MODE}


PO_STATUS = {"01": "Draft", "02": "Active", "03": "In approval", "05": "Released", "08": "Rejected"}


@mcp.tool()
def list_purchase_orders(supplier_id: str | None = None, top: int = 5) -> dict:
    """List SAP purchase orders, optionally only for one supplier ID.

    Returns PO number, supplier, company code, purchasing organisation, order date,
    currency and processing status. `top` is the maximum number of POs (1-20).
    """
    top = sap.clamp_top(top)
    params = {
        "$top": str(top),
        "$orderby": "PurchaseOrderDate desc",
        "$select": "PurchaseOrder,PurchaseOrderType,Supplier,CompanyCode,PurchasingOrganization,"
        "PurchaseOrderDate,DocumentCurrency,PurchasingProcessingStatus",
    }
    try:
        if supplier_id:
            supplier_id = sap.check_id(supplier_id, "supplier_id")
            params["$filter"] = f"Supplier eq '{supplier_id}'"
        rows = sap.odata_get(sap.PO_SERVICE, "A_PurchaseOrder", params)
    except ValueError as exc:
        return _fail(str(exc))
    except sap.SapError as exc:
        return _fail(str(exc))

    if supplier_id:
        rows = [r for r in rows if r.get("Supplier") == supplier_id]
    orders = [
        {
            "purchaseOrder": r.get("PurchaseOrder"),
            "supplierId": r.get("Supplier"),
            "companyCode": r.get("CompanyCode"),
            "purchasingOrg": r.get("PurchasingOrganization"),
            "orderDate": sap.sap_date(r.get("PurchaseOrderDate")),
            "currency": r.get("DocumentCurrency"),
            "status": PO_STATUS.get(r.get("PurchasingProcessingStatus") or "", r.get("PurchasingProcessingStatus")),
        }
        for r in rows[:top]
    ]
    return {"found": bool(orders), "count": len(orders), "purchaseOrders": orders, "source": sap.MODE}


# ---------------------------------------------------------------------------
# Generic read-only access to more SAP APIs (allow-list)
# One tool reaches many standard S/4HANA OData APIs, so we do not need a new function per API.
# Still GET only, still validated, still capped at 20 rows.
# ---------------------------------------------------------------------------

SAP_APIS: dict[str, tuple[str, str, str]] = {
    # name: (OData service, entity set, what it holds)
    "suppliers": ("API_BUSINESS_PARTNER", "A_Supplier", "Supplier master data"),
    "business_partners": ("API_BUSINESS_PARTNER", "A_BusinessPartner", "Business partners (people and companies)"),
    "purchase_orders": ("API_PURCHASEORDER_PROCESS_SRV", "A_PurchaseOrder", "Purchase order headers"),
    "purchase_order_items": ("API_PURCHASEORDER_PROCESS_SRV", "A_PurchaseOrderItem", "Purchase order items: material, quantity, price"),
    "purchase_requisitions": ("API_PURCHASEREQ_PROCESS_SRV", "A_PurchaseRequisitionItem", "Purchase requisition items (demand)"),
    "goods_receipts": ("API_MATERIAL_DOCUMENT_SRV", "A_MaterialDocumentHeader", "Material documents, e.g. goods receipts"),
    "goods_receipt_items": ("API_MATERIAL_DOCUMENT_SRV", "A_MaterialDocumentItem", "Material document items: material, quantity, PO reference"),
    "products": ("API_PRODUCT_SRV", "A_Product", "Product / material master"),
    "supplier_invoices": ("API_SUPPLIERINVOICE_PROCESS_SRV", "A_SupplierInvoice", "Supplier invoices"),
}
SapApi = Literal[tuple(SAP_APIS)]  # becomes an enum in the tool schema, so the AI can only pick these

_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FILTER = re.compile(r"^[A-Za-z0-9_ '\-.:,()/]*$")


def _clean_row(row: dict, max_fields: int = 20) -> dict:
    """Drop OData metadata, links and empty values; convert SAP dates; keep it short for the AI."""
    out = {}
    for key, value in row.items():
        if key.startswith("__") or isinstance(value, dict) or value in ("", None):
            continue
        if isinstance(value, str) and value.startswith("/Date("):
            value = sap.sap_date(value)
        out[key] = value
        if len(out) >= max_fields:
            break
    return out


@mcp.tool()
def list_sap_apis() -> dict:
    """List the SAP S/4HANA APIs that query_sap can read (name, OData service, entity, description)."""
    apis = [{"api": name, "service": svc, "entity": ent, "description": desc} for name, (svc, ent, desc) in SAP_APIS.items()]
    return {"found": True, "count": len(apis), "apis": apis, "source": sap.MODE}


@mcp.tool()
def query_sap(
    api: SapApi,
    filter: str | None = None,
    select: str | None = None,
    orderby: str | None = None,
    top: int = 5,
) -> dict:
    """Read rows from any allowed SAP S/4HANA API (see list_sap_apis). Read-only.

    filter: OData v2 filter, e.g. "Supplier eq '1018'" or "CompanyCode eq '1710' and PurchaseOrderType eq 'NB'".
    select: comma-separated field names to return, e.g. "PurchaseOrder,Supplier,CompanyCode".
    orderby: one field, optionally followed by asc or desc, e.g. "PurchaseOrderDate desc".
    top: maximum rows (1-20). Field names are SAP's own (see api.sap.com for each API).
    """
    service, entity, _ = SAP_APIS[api]
    params = {"$top": str(sap.clamp_top(top))}
    try:
        if filter:
            if len(filter) > 300 or not _FILTER.match(filter):
                raise ValueError("filter has unsupported characters or is too long (max 300).")
            params["$filter"] = filter
        if select:
            fields = [f.strip() for f in select.split(",") if f.strip()]
            if not fields or len(fields) > 25 or not all(_FIELD.match(f) for f in fields):
                raise ValueError("select must be up to 25 comma-separated SAP field names.")
            params["$select"] = ",".join(fields)
        if orderby:
            parts = orderby.split()
            if not (1 <= len(parts) <= 2 and _FIELD.match(parts[0]) and (len(parts) == 1 or parts[1] in ("asc", "desc"))):
                raise ValueError("orderby must be 'Field' or 'Field asc|desc'.")
            params["$orderby"] = " ".join(parts)
        if sap.MODE == "mock" and entity not in ("A_Supplier", "A_PurchaseOrder"):
            return {"found": False, "message": f"No mock sample for {api}; use SAP_MODE=sandbox.", "source": sap.MODE}
        rows = sap.odata_get(service, entity, params)
    except ValueError as exc:
        return _fail(str(exc))
    except sap.SapError as exc:
        return _fail(str(exc))

    rows = [_clean_row(r) for r in rows[: sap.clamp_top(top)]]
    return {"found": bool(rows), "api": api, "endpoint": f"{service}/{entity}", "count": len(rows), "rows": rows,
            "source": sap.MODE}


if __name__ == "__main__":
    sap.log(f"MCP server 'sap-s4hana-readonly' starting over stdio (SAP_MODE={sap.MODE})")
    mcp.run()

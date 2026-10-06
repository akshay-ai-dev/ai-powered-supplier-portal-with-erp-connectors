import sqlite3

from .notifications import list_for_user


def _count(conn: sqlite3.Connection, sql: str, *args) -> int:
    return conn.execute(sql, args).fetchone()[0]


def buyer_dashboard(conn: sqlite3.Connection, user: dict) -> dict:
    # Order data is scoped to the buyer's own POs; inventory and supplier directory are shared.
    uid = user["id"]
    by_status = {
        r["status"]: r["n"]
        for r in conn.execute("SELECT status, COUNT(*) n FROM purchase_orders WHERE created_by = ? GROUP BY status", (uid,))
    }
    spend = conn.execute(
        "SELECT s.supplier_name AS name, ROUND(SUM(po.total_amount),2) AS total FROM purchase_orders po "
        "JOIN suppliers s ON s.id = po.supplier_id WHERE po.status != 'Draft' AND po.created_by = ? "
        "GROUP BY s.id ORDER BY total DESC LIMIT 6",
        (uid,),
    ).fetchall()
    activity = conn.execute(
        "SELECT a.action, a.entity, a.entity_id, a.detail, a.created_at, a.channel, u.name AS user_name FROM audit_logs a "
        "LEFT JOIN users u ON u.id = a.user_id WHERE a.entity IN ('purchase_order','requirement') "
        "AND (a.user_id = ? OR a.entity_id IN (SELECT po_number FROM purchase_orders WHERE created_by = ?) "
        "OR a.entity_id IN (SELECT req_number FROM requirements WHERE created_by = ?)) ORDER BY a.id DESC LIMIT 8",
        (uid, uid, uid),
    ).fetchall()
    return {
        "open_orders": _count(
            conn, "SELECT COUNT(*) FROM purchase_orders WHERE created_by = ? AND status IN ('Draft','Pending','Approved')", uid
        ),
        "inventory_count": _count(conn, "SELECT COUNT(*) FROM inventory"),
        "low_stock_count": _count(conn, "SELECT COUNT(*) FROM inventory WHERE stock_quantity < 20"),
        "supplier_count": _count(conn, "SELECT COUNT(*) FROM suppliers"),
        "orders_by_status": by_status,
        "spend_by_supplier": [dict(r) for r in spend],
        "recent_activity": [dict(r) for r in activity],
    }


def supplier_dashboard(conn: sqlite3.Connection, user: dict) -> dict:
    sid = user.get("supplier_id") or -1
    return {
        "active_orders": _count(
            conn, "SELECT COUNT(*) FROM purchase_orders WHERE supplier_id = ? AND status IN ('Pending','Approved')", sid
        ),
        "pending_deliveries": _count(
            conn,
            "SELECT COUNT(*) FROM purchase_orders WHERE supplier_id = ? AND status = 'Approved' AND delivery_status != 'Delivered'",
            sid,
        ),
        "notifications": list_for_user(conn, user, limit=10),
    }


def inspector_dashboard(conn: sqlite3.Connection, user: dict) -> dict:
    """Goods receiving at a glance. A buyer's own inspector counts that buyer's shipments only."""
    scope_sql, scope_args = ("AND po.created_by = ?", [user["owner_id"]]) if user.get("owner_id") else ("", [])
    by_status = {
        r["status"]: r["n"]
        for r in conn.execute(
            "SELECT s.status, COUNT(*) n FROM shipments s JOIN purchase_orders po ON po.id = s.po_id WHERE 1=1 " + scope_sql + " GROUP BY s.status",
            scope_args,
        )
    }
    return {
        "incoming": by_status.get("Shipped", 0),
        "awaiting_inspection": by_status.get("Arrived", 0),
        "approved": by_status.get("Approved", 0),
        "rejected": by_status.get("Rejected", 0),
        "notifications": list_for_user(conn, user, limit=10),
    }

"""File storage for requirement attachments (drawings, specs) and shipment files (packing lists, photos).
Storage only: access checks live in the services that call this.

Files live under <database dir>/uploads (the persistent volume in Docker) with random names, so a user-supplied
filename never touches the filesystem path. Only a whitelist of extensions is accepted and downloads are always
forced as attachments, so an uploaded file can never be rendered as a page.
"""
import os
import re
import shutil
import sqlite3
import uuid
from pathlib import Path

from ..config import settings
from ..db import now
from .errors import DomainError

MAX_BYTES = 10 * 1024 * 1024
ALLOWED_EXT = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".dwg", ".dxf", ".step", ".stp",
    ".xlsx", ".xls", ".csv", ".txt", ".docx", ".zip",
}


def upload_dir() -> Path:
    path = Path(settings.database_path).resolve().parent / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _clean_name(filename: str) -> str:
    name = os.path.basename((filename or "").replace("\\", "/")).strip()
    name = re.sub(r"[^\w.\- ()]", "_", name)[:120]
    return name or "file"


def store(filename: str, data: bytes) -> dict:
    """Validate and write a file to disk. Returns {filename, stored_name, size}."""
    name = _clean_name(filename)
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXT:
        raise DomainError(f"File type '{ext or 'unknown'}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_EXT))}", 415)
    if not data:
        raise DomainError("The file is empty")
    if len(data) > MAX_BYTES:
        raise DomainError(f"File is larger than {MAX_BYTES // (1024 * 1024)} MB", 413)
    stored = f"{uuid.uuid4().hex}{ext}"
    (upload_dir() / stored).write_bytes(data)
    return {"filename": name, "stored_name": stored, "size": len(data)}


def save(conn: sqlite3.Connection, requirement_id: int, user_id: int, filename: str, data: bytes, content_type: str | None) -> dict:
    f = store(filename, data)
    cur = conn.execute(
        "INSERT INTO attachments (requirement_id, filename, content_type, size, stored_name, uploaded_by, created_at) VALUES (?,?,?,?,?,?,?)",
        (requirement_id, f["filename"], content_type or "application/octet-stream", f["size"], f["stored_name"], user_id, now()),
    )
    return summary(conn, cur.lastrowid)


def summary(conn: sqlite3.Connection, attachment_id: int) -> dict:
    r = conn.execute("SELECT id, requirement_id, filename, size, created_at FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
    return dict(r)


def list_for(conn: sqlite3.Connection, requirement_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, filename, size, created_at FROM attachments WHERE requirement_id = ? ORDER BY id", (requirement_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def path_of(row: sqlite3.Row) -> Path:
    return upload_dir() / row["stored_name"]


def remove(conn: sqlite3.Connection, row: sqlite3.Row) -> None:
    path_of(row).unlink(missing_ok=True)
    conn.execute("DELETE FROM attachments WHERE id = ?", (row["id"],))


def purge_all() -> None:
    d = upload_dir()
    for child in d.iterdir():
        if child.is_file():
            child.unlink(missing_ok=True)
        elif child.is_dir():
            shutil.rmtree(child, ignore_errors=True)

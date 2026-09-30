"""Request message threads (SRS §3.1, §5.1).

One private thread per request per invited supplier. Rules enforced here:
  - a supplier opens only their own thread (data isolation, SRS §8)
  - the request's buyer opens every thread on the request
  - admin can read; inspectors have no access
  - a declined invitation makes the thread read-only
Every new message notifies the other party (bell + email).
"""

import mimetypes
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import CurrentUser, SessionDep
from app.config import get_settings
from app.db.models import Attachment, Message, MessageThread
from app.notifications import directory
from app.notifications.directory import User
from app.notifications.service import notify

router = APIRouter(tags=["messages"])

MAX_TEXT = 4000
MAX_FILES = 5


# ---------------------------------------------------------------- response shapes


class AttachmentOut(BaseModel):
    id: int
    fileName: str
    fileType: str
    sizeBytes: int
    url: str


class MessageOut(BaseModel):
    id: int
    author: str
    authorName: str
    authorRole: str
    text: str
    sentAt: datetime
    attachments: list[AttachmentOut]


class ThreadInfo(BaseModel):
    requestId: str
    supplierId: str
    supplierName: str
    invitationStatus: Literal["invited", "declined", "responded"]
    canPost: bool


class ThreadResponse(BaseModel):
    thread: ThreadInfo
    messages: list[MessageOut]


# ---------------------------------------------------------------- access rules


def _check_access(user: User, request_id: str, supplier_id: str) -> str:
    """Return the invitation status if the user may read this thread, else raise."""
    status = directory.get_invitation(request_id, supplier_id)
    if user.role == "supplier":
        if user.supplier_id != supplier_id:
            raise HTTPException(403, "You can only open your own message thread.")
    elif user.role == "buyer":
        if directory.request_buyer(request_id) != user.id:
            raise HTTPException(403, "You are not the buyer on this request.")
    elif user.role != "admin":
        raise HTTPException(403, "Your role cannot open message threads.")
    if status is None:
        raise HTTPException(404, f"{supplier_id} is not invited to {request_id}.")
    return status


def _can_post(user: User, status: str) -> bool:
    return user.role in ("buyer", "supplier") and status != "declined"


def _get_or_create_thread(session: Session, request_id: str, supplier_id: str) -> MessageThread:
    thread = session.exec(
        select(MessageThread).where(
            MessageThread.request_id == request_id, MessageThread.supplier_id == supplier_id
        )
    ).first()
    if thread is None:
        thread = MessageThread(request_id=request_id, supplier_id=supplier_id)
        session.add(thread)
        session.commit()
        session.refresh(thread)
    return thread


def _message_out(session: Session, m: Message) -> MessageOut:
    author = directory.get_user(m.author)
    files = session.exec(
        select(Attachment)
        .where(Attachment.owner_type == "message", Attachment.owner_id == m.id)
        .order_by(Attachment.id)
    ).all()
    return MessageOut(
        id=m.id,
        author=m.author,
        authorName=author.name if author else m.author,
        authorRole=m.author_role,
        text=m.text,
        sentAt=m.sent_at,
        attachments=[
            AttachmentOut(
                id=a.id,
                fileName=a.file_name,
                fileType=a.file_type,
                sizeBytes=a.size_bytes,
                url=f"/attachments/{a.id}",
            )
            for a in files
        ],
    )


# ---------------------------------------------------------------- endpoints


@router.get("/requests/{request_id}/threads/{supplier_id}/messages", response_model=ThreadResponse)
def get_thread(
    request_id: str, supplier_id: str, user: CurrentUser, session: SessionDep
) -> ThreadResponse:
    status = _check_access(user, request_id, supplier_id)
    thread = _get_or_create_thread(session, request_id, supplier_id)
    messages = session.exec(
        select(Message).where(Message.thread_id == thread.id).order_by(Message.sent_at, Message.id)
    ).all()
    return ThreadResponse(
        thread=ThreadInfo(
            requestId=request_id,
            supplierId=supplier_id,
            supplierName=directory.supplier_name(supplier_id),
            invitationStatus=status,
            canPost=_can_post(user, status),
        ),
        messages=[_message_out(session, m) for m in messages],
    )


def _save_upload(upload: UploadFile, max_bytes: int, allowed: set[str]) -> tuple[str, str, int]:
    """Validate and store one file. Returns (storage_path, mime_type, size)."""
    name = Path(upload.filename or "file").name
    ext = Path(name).suffix.lower().lstrip(".")
    if ext not in allowed:
        raise HTTPException(400, f"{name}: file type not allowed ({', '.join(sorted(allowed))}).")
    rel = Path("messages") / f"{uuid.uuid4().hex}.{ext}"
    dest = Path(get_settings().file_storage_path) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with dest.open("wb") as out:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(400, f"{name}: larger than {max_bytes // (1024 * 1024)} MB.")
            out.write(chunk)
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return str(rel), mime, size


@router.post(
    "/requests/{request_id}/threads/{supplier_id}/messages",
    response_model=MessageOut,
    status_code=201,
)
def post_message(
    request_id: str,
    supplier_id: str,
    user: CurrentUser,
    session: SessionDep,
    background: BackgroundTasks,
    text: Annotated[str, Form()] = "",
    files: Annotated[list[UploadFile], File()] = [],  # noqa: B006
) -> MessageOut:
    status = _check_access(user, request_id, supplier_id)
    if not _can_post(user, status):
        if status == "declined":
            raise HTTPException(403, "The supplier declined this request. The thread is read-only.")
        raise HTTPException(403, "Your role can read this thread but not post.")
    text = text.strip()
    if not text and not files:
        raise HTTPException(400, "Write a message or attach a file.")
    if len(text) > MAX_TEXT:
        raise HTTPException(400, f"Message is too long (max {MAX_TEXT} characters).")
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"Attach at most {MAX_FILES} files.")

    s = get_settings()
    saved = [
        _save_upload(f, s.max_upload_size_mb * 1024 * 1024, s.upload_extensions) for f in files
    ]

    thread = _get_or_create_thread(session, request_id, supplier_id)
    msg = Message(thread_id=thread.id, author=user.id, author_role=user.role, text=text)
    session.add(msg)
    session.commit()
    session.refresh(msg)
    for (rel, mime, size), upload in zip(saved, files, strict=True):
        session.add(
            Attachment(
                owner_type="message",
                owner_id=msg.id,
                file_name=Path(upload.filename or "file").name,
                file_type=mime,
                size_bytes=size,
                storage_path=rel,
                uploaded_by=user.id,
            )
        )
    session.commit()

    # Notify the other party (SRS §4 step 3).
    if user.role == "supplier":
        buyer = directory.request_buyer(request_id)
        recipients = [buyer] if buyer else []
    else:
        recipients = [u.id for u in directory.supplier_users(supplier_id)]
    notify(
        session,
        recipients,
        "new_message",
        request_id,
        context={"author_name": user.name, "supplier_id": supplier_id},
        background=background,
    )
    return _message_out(session, msg)


@router.get("/attachments/{attachment_id}")
def download_attachment(attachment_id: int, user: CurrentUser, session: SessionDep) -> FileResponse:
    """Download a message attachment; the same access rules as the thread apply."""
    att = session.get(Attachment, attachment_id)
    if att is None or att.owner_type != "message":
        raise HTTPException(404, "Attachment not found.")
    msg = session.get(Message, att.owner_id)
    thread = session.get(MessageThread, msg.thread_id) if msg else None
    if thread is None:
        raise HTTPException(404, "Attachment not found.")
    _check_access(user, thread.request_id, thread.supplier_id)
    path = Path(get_settings().file_storage_path) / att.storage_path
    if not path.is_file():
        raise HTTPException(404, "File is missing from storage.")
    return FileResponse(path, media_type=att.file_type, filename=att.file_name)

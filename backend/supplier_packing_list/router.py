"""The authenticated, buyer-facing draft-extraction endpoint.

    POST /api/requirements/extract-draft   (multipart/form-data)

A buyer uploads one document (PDF, PNG, JPEG, or WEBP) and gets back a normalised
draft of the fields the extractors could read, for the frontend to map onto the
"New requirement" form so the buyer can review, edit, and then submit. It does NOT
create a requirement, attach a file, or post to the ERP — it is pre-fill only. The
buyer submits later through the existing ``POST /api/requirements`` flow, unchanged.

See ``backend/supplier_packing_list/README.md`` for the request/response contract and the mapping
from the extracted fields onto the requirement form.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, UploadFile

from app.deps import require_buyer
from app.services.errors import DomainError

from .config import MAX_UPLOAD_BYTES
from .schemas import DraftExtraction
from .service import extract_draft

router = APIRouter(prefix="/api", tags=["Requirements & Quotes"])


def _clean_basename(name: str | None) -> str:
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    return base[:200] or "upload"


@router.post(
    "/requirements/extract-draft",
    response_model=DraftExtraction,
    response_model_exclude_none=False,
    summary="Draft extraction of an uploaded document (PDF or image) to pre-fill the New requirement form — no requirement is created",
)
async def extract_requirement_draft(
    file: UploadFile = File(..., description="The document: PDF, PNG, JPEG, or WEBP"),
    # require_buyer = buyer or admin; everyone else gets 403, no token gets 401.
    user: dict = Depends(require_buyer),
) -> DraftExtraction:
    if not file.filename:
        raise DomainError("No file was uploaded. Send it in the multipart field 'file'.", 400)
    filename = _clean_basename(file.filename)

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise DomainError(
            f"The file is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.", 413
        )

    # Extraction only: no DB write, no requirement, no ERP call.
    return await extract_draft(filename, data)

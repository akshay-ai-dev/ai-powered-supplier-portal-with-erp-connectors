"""Buyer New-requirement pre-fill endpoint.

A buyer uploads a purchase requisition / request / RFQ brief (PDF or image) and gets back a reviewable
*draft* for the New requirement form (item name, specs/notes, requested quantity, target unit price,
needed-by date, quote deadline) with per-field evidence and warnings. It creates NOTHING: no
requirement, no attachment, no ERP call, no database write. The buyer reviews and edits the draft,
then the existing `POST /api/requirements` flow persists it. The ERP system stays a buyer choice on
the form and is never extracted.

Kept in its own router so the buyer requirement concern is separate from the supplier shipment
pre-fill in `router.py`; both share the `/api/extraction-prefill` prefix. Access is buyer/admin only.
"""

from fastapi import APIRouter, Depends, File, UploadFile

from app.config import settings
from app.deps import require_buyer
from app.services.errors import DomainError

from . import buyer_extractor

router = APIRouter(prefix="/api/extraction-prefill", tags=["Extraction Prefill"])


@router.post(
    "/requirements",
    summary="Extract a New-requirement draft from a document (buyer; saves nothing)",
)
def extract_for_requirement(
    file: UploadFile = File(...),
    user: dict = Depends(require_buyer),  # authorize before any upload read or network call
):
    if not settings.openai_api_key:
        raise DomainError(
            "Document extraction is not configured (no OPENAI_API_KEY). "
            "You can still fill the form yourself.",
            503,
        )
    data = file.file.read(buyer_extractor.MAX_BYTES + 1)  # never read more than the limit + 1 byte
    return buyer_extractor.extract(file.filename or "file", data, file.content_type)

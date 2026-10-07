"""The one consistent draft-extraction response returned by both the PDF and the
image paths, plus the field-issue sub-model.

The draft pre-fills the buyer's "New requirement" form (it is uploaded before any
requirement exists). See ``backend/supplier_packing_list/README.md`` for the field -> form mapping.

Design rules baked into the types:
- Missing scalars are ``null``; missing lists are ``[]`` (never invented).
- Every missing or uncertain value is explained in ``fieldIssues``.
- ``shipDate`` is only ever a shipped/dispatch date. When it was inferred from a
  generic document date (PDF path), ``shipDateInferred`` is ``true`` and a
  ``shipDate`` field issue says so, so a document date is never silently trusted
  as the ship date.
- ``unitOfMeasure`` is populated by the PDF path only; the image six-field schema
  has no unit, so it stays ``null`` there (a warning records why).
- This is a DRAFT: nothing here creates a requirement, writes to the ERP, or
  submits anything. The buyer reviews/edits, then submits via POST /api/requirements.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SourceType = Literal["pdf", "image"]
ExtractionStatus = Literal["extracted", "conversion_error"]
IssueSeverity = Literal["review", "warning", "info"]


class FieldIssue(BaseModel):
    """One thing the buyer should check before submitting. ``severity``:
    ``review`` = please confirm this value; ``warning`` = missing/weak; ``info`` =
    note."""

    field: str
    severity: IssueSeverity = "review"
    code: str
    message: str
    rawValue: Any | None = None
    page: int | None = None


class ExtractorInfo(BaseModel):
    type: SourceType
    version: str | None = None
    model: str | None = None  # image path only


class DraftExtraction(BaseModel):
    """The single normalised draft both paths return."""

    sourceType: SourceType
    sourceFile: str
    status: ExtractionStatus = "extracted"

    shipDate: str | None = None
    shipDateInferred: bool = False
    carrier: str | None = None
    trackingNumbers: list[str] = Field(default_factory=list)
    shippedQuantity: float | None = None
    unitOfMeasure: str | None = None
    lotNumbers: list[str] = Field(default_factory=list)
    serialNumbers: list[str] = Field(default_factory=list)

    items: list[dict[str, Any]] = Field(default_factory=list)
    fieldIssues: list[FieldIssue] = Field(default_factory=list)

    # PDF path only; image path leaves these empty.
    evidence: dict[str, Any] = Field(default_factory=dict)
    conversionError: dict[str, Any] | None = None

    extractor: ExtractorInfo
    warnings: list[str] = Field(default_factory=list)

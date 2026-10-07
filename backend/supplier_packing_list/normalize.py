"""Turn each extractor's native output into one :class:`DraftExtraction`.

No value is invented here: fields absent from a path stay ``null`` / ``[]`` and are
explained with a field issue. The PDF path's evidence and review flags are
preserved as-is; the image path's six fields are mapped straight across and the
missing ones are flagged the same way the PDF extractor flags them.
"""

from __future__ import annotations

from typing import Any

from .image.config import SCHEMA_VERSION
from .image.schemas import ShipmentExtraction
from .pdf.isolation import is_conversion_error
from .schemas import DraftExtraction, ExtractorInfo, FieldIssue

# The code the PDF extractor emits when it fell back to a generic document date.
_INFERRED_SHIP_DATE_CODE = "inferred_from_document_date"

# Six fields that must always be present or explained (mirrors the PDF extractor's
# CORE_FIELDS). serialNumbers absence is only informational.
_IMAGE_CORE_FIELDS = (
    "shipDate",
    "carrier",
    "trackingNumbers",
    "shippedQuantity",
    "lotNumbers",
    "serialNumbers",
)

IMAGE_NO_UNIT_WARNING = (
    "Image extraction does not capture a unit of measure. Confirm the unit before "
    "relying on any quantity comparison."
)


def _issue(raw: dict[str, Any]) -> FieldIssue:
    return FieldIssue(
        field=raw.get("field", ""),
        severity=raw.get("severity", "review"),
        code=raw.get("code", ""),
        message=raw.get("message", ""),
        rawValue=raw.get("rawValue"),
        page=raw.get("page"),
    )


def from_pdf(result: dict[str, Any], source_file: str) -> DraftExtraction:
    """Normalise the dict returned by ``supplier_packing_list.pdf.isolation.convert_isolated``."""
    version = result.get("extractorVersion")
    if is_conversion_error(result):
        conv = result.get("conversionError", {})
        return DraftExtraction(
            sourceType="pdf",
            sourceFile=source_file,
            status="conversion_error",
            conversionError=conv,
            fieldIssues=[
                FieldIssue(
                    field="document",
                    severity="review",
                    code="conversion_error",
                    message=(
                        "The PDF could not be converted, so no fields were extracted. "
                        "Enter the shipment details manually. " + str(conv.get("message", ""))
                    ).strip(),
                )
            ],
            extractor=ExtractorInfo(type="pdf", version=version),
            warnings=["PDF conversion failed; the draft contains no extracted values."],
        )

    issues = [_issue(i) for i in result.get("fieldIssues", []) or []]
    ship_date_inferred = any(i.code == _INFERRED_SHIP_DATE_CODE for i in issues)
    return DraftExtraction(
        sourceType="pdf",
        sourceFile=source_file,
        status="extracted",
        shipDate=result.get("shipDate"),
        shipDateInferred=ship_date_inferred,
        carrier=result.get("carrier"),
        trackingNumbers=list(result.get("trackingNumbers") or []),
        shippedQuantity=result.get("shippedQuantity"),
        unitOfMeasure=result.get("unitOfMeasure"),
        lotNumbers=list(result.get("lotNumbers") or []),
        serialNumbers=list(result.get("serialNumbers") or []),
        items=list(result.get("items") or []),
        fieldIssues=issues,
        evidence=result.get("evidence") or {},
        extractor=ExtractorInfo(type="pdf", version=version),
    )


def from_image(extraction: ShipmentExtraction, source_file: str, model: str) -> DraftExtraction:
    """Normalise a validated six-key :class:`ShipmentExtraction`."""
    data = extraction.model_dump(mode="json")  # dates -> ISO strings
    ship_date = data.get("shipDate")
    carrier = data.get("carrier")
    tracking = list(data.get("trackingNumbers") or [])
    shipped_qty = data.get("shippedQuantity")
    lots = list(data.get("lotNumbers") or [])
    serials = list(data.get("serialNumbers") or [])

    present = {
        "shipDate": ship_date,
        "carrier": carrier,
        "trackingNumbers": tracking,
        "shippedQuantity": shipped_qty,
        "lotNumbers": lots,
        "serialNumbers": serials,
    }
    issues: list[FieldIssue] = []
    for field in _IMAGE_CORE_FIELDS:
        value = present[field]
        if value in (None, []):
            severity = "info" if field == "serialNumbers" else "warning"
            issues.append(
                FieldIssue(
                    field=field,
                    severity=severity,
                    code="not_found",
                    message=f"No {field} was found in the image.",
                )
            )

    return DraftExtraction(
        sourceType="image",
        sourceFile=source_file,
        status="extracted",
        shipDate=ship_date,
        shipDateInferred=False,  # the image prompt returns a ship date or null; it never infers
        carrier=carrier,
        trackingNumbers=tracking,
        shippedQuantity=shipped_qty,
        unitOfMeasure=None,  # not in the six-field image schema
        lotNumbers=lots,
        serialNumbers=serials,
        items=[],
        fieldIssues=issues,
        evidence={},
        extractor=ExtractorInfo(type="image", version=SCHEMA_VERSION, model=model),
        warnings=[IMAGE_NO_UNIT_WARNING],
    )

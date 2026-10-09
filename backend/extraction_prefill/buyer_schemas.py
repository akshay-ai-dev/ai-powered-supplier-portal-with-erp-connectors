"""Pydantic models for the buyer *New requirement* draft the buyer reviews.

Snake_case keys match the `RequirementCreate` fields (title, description, quantity, target_price,
needed_by, quote_deadline) so the New requirement page maps them straight across. `evidence` and
`field_issues` are a review aid produced by the model; they are not verified proof and are never
persisted. `Evidence`, `FieldIssue` and `Reference` are reused from the shipment draft schema so the
frontend handles one evidence/issue shape across both prefill flows.

These fields are separate from the supplier shipment draft: `quantity` here is a *requested* quantity
(never a shipped quantity), and there is no carrier / tracking / lot / serial. The ERP system is not
part of the draft; the buyer selects it on the form.
"""

from pydantic import BaseModel, Field

from .schemas import Evidence, FieldIssue, Reference

__all__ = ["RequirementDraftItem", "RequirementDraft", "Evidence", "FieldIssue", "Reference"]


class RequirementDraftItem(BaseModel):
    """One requested item. Used to surface every item when a document lists several, so the buyer
    chooses which one this requirement is for rather than having quantities combined."""

    item_name: str | None = None
    specs: str | None = None
    quantity: float | None = None
    unit_of_measure: str | None = None
    target_price: float | None = None


class RequirementDraft(BaseModel):
    """The buyer requirement fields plus review context. A requested quantity, target *unit* price,
    needed-by date and quote deadline — never a shipped quantity or an invented price/date."""

    title: str | None = Field(default=None, description="Item name for the requirement")
    description: str | None = Field(default=None, description="Specs / notes")
    quantity: float | None = Field(default=None, description="Requested quantity (not shipped)")
    target_price: float | None = Field(default=None, description="Target unit price")
    needed_by: str | None = Field(default=None, description="ISO date, e.g. 2026-11-30")
    quote_deadline: str | None = Field(
        default=None,
        description="ISO 8601 date-time (document's local wall-clock; see quote_deadline_tz)",
    )
    quote_deadline_tz: str | None = Field(
        default=None,
        description="Time zone printed for the quote deadline (e.g. CST, ET, UTC), or null",
    )
    items: list[RequirementDraftItem] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    field_issues: list[FieldIssue] = Field(default_factory=list)

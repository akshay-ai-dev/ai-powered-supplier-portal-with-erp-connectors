"""Pydantic models for the extraction draft the buyer reviews.

Snake_case keys match the `RequirementCreate` fields so the New requirement page maps them
straight across. `evidence` and `field_issues` are a review aid produced by the model; they are
not verified proof and are never persisted.
"""

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["review", "warning", "info"]


class Evidence(BaseModel):
    field: str
    page: int | None = None
    text: str = ""


class FieldIssue(BaseModel):
    field: str
    severity: Severity = "info"
    code: str = ""
    message: str = ""


class DraftItem(BaseModel):
    item_number: str | None = None
    description: str | None = None
    quantity_ordered: float | None = None
    quantity_shipped: float | None = None
    quantity_backordered: float | None = None
    unit_of_measure: str | None = None


class Reference(BaseModel):
    value: str
    label: str | None = None
    page: int | None = None
    kind: str = "other"


class ExtractionDraft(BaseModel):
    """The six reviewed fields (ship date, carrier, tracking/lot/serial numbers, shipped quantity)
    plus review context. Shipped quantity is deliberately separate from any requested quantity and
    is never mapped onto the requirement's requested quantity."""

    ship_date: str | None = Field(default=None, description="ISO date, e.g. 2024-01-16")
    carrier: str | None = None
    tracking_numbers: list[str] = Field(default_factory=list)
    shipped_quantity: float | None = None
    unit_of_measure: str | None = None
    lot_numbers: list[str] = Field(default_factory=list)
    serial_numbers: list[str] = Field(default_factory=list)
    items: list[DraftItem] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    field_issues: list[FieldIssue] = Field(default_factory=list)

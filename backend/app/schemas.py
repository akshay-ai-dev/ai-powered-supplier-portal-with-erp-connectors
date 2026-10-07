import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, EmailStr, Field

_PHONE_CHARS = re.compile(r"^\+?[0-9 ()./-]+$")


def _validate_phone(value: str | None) -> str | None:
    """Digits with an optional leading +, and spaces ( ) . - / as separators. 7 to 15 digits (E.164 maximum)."""
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return ""
    if not _PHONE_CHARS.match(value):
        raise ValueError("Phone number may only contain digits, spaces, ( ) - . / and a leading +")
    digits = re.sub(r"\D", "", value)
    if not 7 <= len(digits) <= 15:
        raise ValueError("Phone number must have between 7 and 15 digits")
    if "+" in value[1:]:
        raise ValueError("The + sign is only allowed at the start")
    return value


Phone = Annotated[str, AfterValidator(_validate_phone), Field(max_length=25)]

Role = Literal["buyer", "supplier"]
POStatus = Literal["Draft", "Pending", "Approved", "Closed"]
DeliveryStatus = Literal["Not Shipped", "In Transit", "Delivered", "Rejected"]


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Role


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    supplier_id: int | None = None
    owner_id: int | None = None
    owner_name: str | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class SupplierIn(BaseModel):
    supplier_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: Phone = ""
    address: str = ""


class SupplierUpdate(BaseModel):
    supplier_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: Phone | None = None
    address: str | None = None


class POItemIn(BaseModel):
    item_code: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    unit_price: float = Field(ge=0)


class POCreate(BaseModel):
    supplier_id: int
    items: list[POItemIn] = Field(min_length=1)
    submit: bool = Field(default=False, description="Create as Pending instead of Draft")


class POUpdate(BaseModel):
    status: POStatus | None = None
    delivery_status: DeliveryStatus | None = None
    items: list[POItemIn] | None = Field(default=None, min_length=1)


class InventoryCreate(BaseModel):
    item_code: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    description: str = Field(min_length=1, max_length=200)
    stock_quantity: int = Field(default=0, ge=0)
    warehouse: str = Field(default="MAIN", max_length=60)


class InventoryUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=200)
    stock_quantity: int | None = Field(default=None, ge=0)
    warehouse: str | None = Field(default=None, min_length=1, max_length=60)


class AdminUserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Literal["buyer", "supplier", "admin", "inspector"]


class AdminUserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class TeamInspectorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(
        min_length=8,
        max_length=128,
        description="Give it to the inspector; they can ask you to reset it",
    )


class TeamInspectorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class ResetIn(BaseModel):
    confirm: str = Field(description='Must be the literal string "RESET"')


def _clean_identifier_list(values: list[str] | None) -> list[str]:
    """Trim, drop blanks, dedupe (first-seen order). Used for lot/serial lists."""
    if not values:
        return []
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))[:500]


IdentifierList = Annotated[
    list[Annotated[str, Field(max_length=120)]],
    AfterValidator(_clean_identifier_list),
    Field(max_length=500),
]


class RequirementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    item_code: str | None = None
    # The buyer's REQUESTED quantity. Kept distinct from any shipped quantity on an
    # uploaded document (the supplier_packing_list draft returns that separately and it is never written here).
    quantity: int = Field(gt=0)
    target_price: float | None = Field(default=None, ge=0)
    needed_by: str | None = Field(default=None, description="ISO date, e.g. 2026-11-30")
    # Optional shipping details, typically pre-filled from an uploaded document via the
    # supplier_packing_list draft-extraction endpoint, then reviewed/edited by the buyer before posting.
    ship_date: str | None = Field(
        default=None,
        description="ISO date the goods shipped per an uploaded document, e.g. 2026-02-10",
    )
    carrier: str = Field(default="", max_length=120)
    tracking_number: str = Field(default="", max_length=200)
    lot_numbers: IdentifierList = Field(default_factory=list)
    serial_numbers: IdentifierList = Field(default_factory=list)
    erp: Literal["sap", "infor"] = "sap"
    quote_deadline: str | None = Field(
        default=None, description="ISO 8601 date-time (UTC if no offset). Empty = no deadline."
    )
    open_to_all: bool = Field(
        default=False, description="Visible to every supplier, including ones who join later."
    )
    supplier_ids: list[int] = Field(
        default_factory=list,
        description="Suppliers to invite (ignored when open_to_all). Empty and not open_to_all = invite all current suppliers.",
    )


class DeadlineIn(BaseModel):
    quote_deadline: str | None = Field(
        default=None, description="New ISO 8601 deadline in the future, or null to clear it"
    )


class InviteIn(BaseModel):
    supplier_ids: list[int] = Field(min_length=1)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    supplier_id: int | None = Field(
        default=None, description="Buyers: which supplier's thread. Suppliers: ignored."
    )


class DeclineIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class QuoteIn(BaseModel):
    unit_price: float = Field(ge=0)
    lead_time_days: int = Field(ge=0, le=730)
    message: str = Field(default="", max_length=1000)


class AwardIn(BaseModel):
    quote_id: int


class ShipmentItemIn(BaseModel):
    item_code: str = Field(min_length=1)
    quantity: int = Field(gt=0)


class ShipmentCreate(BaseModel):
    carrier: str = Field(default="", max_length=80)
    tracking_no: str = Field(default="", max_length=80)
    expected_arrival: str | None = Field(default=None, description="ISO date")
    notes: str = Field(default="", max_length=1000)
    items: list[ShipmentItemIn] = Field(min_length=1)
    unit_inspection: bool = Field(
        default=False,
        description="Give every unit its own QR code so the inspector can test them one by one",
    )
    replaces_shipment_id: int | None = Field(
        default=None,
        description="Id of an inspected shipment on this order whose faulty, missing or rejected units this one replaces (see GET /api/purchase-orders/{id}/to-ship)",
    )


class ArrivalLine(BaseModel):
    item_code: str
    quantity_received: int = Field(ge=0)


class ArrivalIn(BaseModel):
    lines: list[ArrivalLine] = Field(
        default_factory=list,
        description="Received quantity per item. Not used for shipments with QR-coded units: the scanned units are the received quantity.",
    )
    notes: str = Field(default="", max_length=1000)


class InspectionIn(BaseModel):
    decision: Literal["approve", "reject"]
    notes: str = Field(default="", max_length=1000)
    reason: str = Field(default="", max_length=500, description="Required when rejecting")
    checks: dict[str, bool] = Field(
        default_factory=dict,
        description="Quality checklist: packaging, specification, condition, documentation. Approving needs all four true.",
    )
    improvement: str = Field(
        default="",
        max_length=1000,
        description="What the supplier must fix (sent to them when rejecting)",
    )
    override_reason: str = Field(
        default="",
        max_length=500,
        description="Unit-level lots: required when the decision goes against what the accuracy threshold suggests",
    )


class TokenCreate(BaseModel):
    name: str = Field(
        min_length=1, max_length=80, description="For example the laptop or agent that will use it"
    )
    scope: Literal["read", "write"] = Field(
        default="read", description="read = look things up; write = read + create Drafts"
    )
    expires_in_days: int | None = Field(
        default=90, ge=1, le=365, description="Null = never expires"
    )


class ScanIn(BaseModel):
    code: str = Field(min_length=1, max_length=120, description="The text of a unit's QR code")


class UnitResultIn(BaseModel):
    result: Literal["OK", "Faulty"] | None = Field(
        default=None, description="Omit to save readings or notes without deciding"
    )
    checks: dict[str, bool] | None = Field(
        default=None, description="packaging, specification, condition, documentation"
    )
    readings: dict[str, str | float | int | bool | None] | None = Field(
        default=None, description="Test field id -> value"
    )
    defect_type: str = Field(default="", max_length=40, description="Required when Faulty")
    notes: str | None = Field(default=None, max_length=1000)


class UnitBulkIn(BaseModel):
    action: Literal["ok", "set_field"]
    codes: list[str] | None = Field(default=None, max_length=2000)
    all_pending: bool = False
    item_code: str | None = None
    field_id: int | None = None
    value: str | float | int | bool | None = None


class TestFieldIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    type: Literal["pass_fail", "number", "text"]
    unit_label: str = Field(default="", max_length=20)
    min_value: float | None = None
    max_value: float | None = None
    required: bool = False
    item_code: str | None = Field(
        default=None, max_length=40, description="Limit the field to one item of the shipment"
    )
    save_template: bool = Field(
        default=False, description="Also start future shipments of this item with the field"
    )


class TestFieldUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    type: Literal["pass_fail", "number", "text"] | None = None
    unit_label: str | None = Field(default=None, max_length=20)
    min_value: float | None = None
    max_value: float | None = None
    required: bool | None = None

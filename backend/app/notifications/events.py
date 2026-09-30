"""The 10 notification events (SRS §3.1) and their text.

Each event has a bell title, a body, and a portal link. Placeholders are filled from
the `context` passed to notify(). Who receives each event (SRS §4) is decided by the
caller, listed here for reference.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EventSpec:
    title: str
    body: str
    link: str
    recipients: str  # documentation only (SRS §4)


EVENTS: dict[str, EventSpec] = {
    "invited": EventSpec(
        "New request {record_id}",
        "You have been invited to quote on {record_id}. Responses are due {deadline}.",
        "/requests/{record_id}",
        "Invited suppliers",
    ),
    "response_received": EventSpec(
        "Response received on {record_id}",
        "{supplier_name} submitted a response to {record_id}.",
        "/requests/{record_id}",
        "Buyer",
    ),
    "deadline_reached": EventSpec(
        "Deadline reached on {record_id}",
        "The response deadline for {record_id} has passed. The request is now locked.",
        "/requests/{record_id}",
        "Buyer",
    ),
    "awarded": EventSpec(
        "You won {record_id}",
        "Your response to {record_id} was awarded. Purchase order {po_number} is available.",
        "/requests/{record_id}",
        "Winning supplier",
    ),
    "not_awarded": EventSpec(
        "{record_id} was awarded to another supplier",
        "Thank you for responding to {record_id}. It was awarded to another supplier.",
        "/requests/{record_id}",
        "Other responding suppliers",
    ),
    "shipment_submitted": EventSpec(
        "Shipment {record_id} submitted",
        "{supplier_name} submitted shipment {record_id} for {request_id}.",
        "/shipments/{record_id}",
        "Buyer, Inspector",
    ),
    "arrived": EventSpec(
        "Shipment {record_id} arrived",
        "Shipment {record_id} arrived and is waiting for inspection.",
        "/shipments/{record_id}",
        "Buyer",
    ),
    "inspection_result": EventSpec(
        "Shipment {record_id} {result}",
        "The inspection of shipment {record_id} is complete: {result}.",
        "/shipments/{record_id}",
        "Buyer, Supplier",
    ),
    "erp_change_flagged": EventSpec(
        "ERP change on {record_id}",
        "The requisition behind {record_id} changed in the ERP. Review and update or cancel.",
        "/requests/{record_id}",
        "Buyer",
    ),
    "new_message": EventSpec(
        "New message on {record_id}",
        "{author_name} sent you a message on {record_id}.",
        "/requests/{record_id}?thread={supplier_id}",
        "The other party in the thread",
    ),
}


class _Blank(dict):
    """Leave unknown placeholders readable instead of raising KeyError."""

    def __missing__(self, key: str) -> str:
        return "-"


def render(event: str, record_id: str, context: dict | None = None) -> tuple[str, str, str]:
    if event not in EVENTS:
        raise ValueError(f"Unknown notification event: {event}")
    spec = EVENTS[event]
    values = _Blank(context or {}, record_id=record_id)
    return (
        spec.title.format_map(values),
        spec.body.format_map(values),
        spec.link.format_map(values),
    )

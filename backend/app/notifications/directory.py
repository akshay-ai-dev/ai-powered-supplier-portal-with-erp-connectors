"""Demo users and invitations for the communication slice.

STAND-IN: the role picker (Slice 1) and the Request/Invitation tables (Slice 2) are
built by other teammates. Until they exist, this module answers the two questions the
communication code needs:
  - who is the current user?            -> get_user()
  - is this supplier invited, and who is the request's buyer?  -> get_invitation(), request_buyer()
Swap these functions for real DB lookups later; nothing else needs to change.

Demo data only (SRS §8): fictional people, companies and @demo.local addresses.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    id: str
    name: str
    role: str  # buyer | supplier | inspector | admin
    email: str
    supplier_id: str | None = None  # set for supplier accounts


USERS: dict[str, User] = {
    u.id: u
    for u in [
        User("buyer-1", "Priya Sharma", "buyer", "priya.sharma@srs.demo.local"),
        User("inspector-1", "Tom Becker", "inspector", "tom.becker@srs.demo.local"),
        User("admin-1", "Portal Admin", "admin", "admin@srs.demo.local"),
        User("sup-apex", "Apex Hydraulics", "supplier", "sales@apex.demo.local", "SUP-SAP-01"),
        User("sup-delta", "Delta Precision", "supplier", "orders@delta.demo.local", "SUP-SAP-02"),
        User("sup-orion", "Orion Castings", "supplier", "rfq@orion.demo.local", "SUP-SAP-03"),
        User("sup-nordic", "Nordic Gearworks", "supplier", "sales@nordic.demo.local", "SUP-LN-01"),
    ]
}

SUPPLIER_NAMES = {
    "SUP-SAP-01": "Apex Hydraulics",
    "SUP-SAP-02": "Delta Precision",
    "SUP-SAP-03": "Orion Castings",
    "SUP-LN-01": "Nordic Gearworks",
}

# (requestId, supplierId) -> invitation status: invited | declined | responded
INVITATIONS: dict[tuple[str, str], str] = {
    ("REQ-0001", "SUP-SAP-01"): "responded",
    ("REQ-0001", "SUP-SAP-02"): "invited",
    ("REQ-0001", "SUP-SAP-03"): "declined",
    ("REQ-0002", "SUP-LN-01"): "invited",
}

REQUEST_BUYER = {"REQ-0001": "buyer-1", "REQ-0002": "buyer-1"}


def get_user(user_id: str) -> User | None:
    return USERS.get(user_id)


def supplier_users(supplier_id: str) -> list[User]:
    return [u for u in USERS.values() if u.supplier_id == supplier_id]


def supplier_name(supplier_id: str) -> str:
    return SUPPLIER_NAMES.get(supplier_id, supplier_id)


def get_invitation(request_id: str, supplier_id: str) -> str | None:
    return INVITATIONS.get((request_id, supplier_id))


def request_buyer(request_id: str) -> str | None:
    return REQUEST_BUYER.get(request_id)

"""Deterministic clean-up and validation for the buyer requirement draft, after the model returns.

Only rules that reliably add value without re-guessing the document:
  * trim blank strings to null;
  * never silently combine or pick when several items are requested — force the multi-item review so
    the buyer chooses one item, and null the single-item fields (title/quantity/target_price) with a
    single "choose an item" message (no duplicate "not found" alongside it);
  * resolve the quote deadline's time zone to a correct UTC offset (daylight-saving aware) when the
    document states one, and keep the document's local wall-clock; when the zone is unclear, leave the
    time naive and flag it for review rather than mislabelling it UTC;
  * flag a needed-by / quote deadline that is already in the past;
  * guarantee a field-level note for every missing core field, so the buyer always sees "not found"
    rather than a silently blank field.

The model is asked to flag relative/ambiguous dates and non-target prices itself; the helpers here are
exposed for tests and belt-and-braces use. Nothing here invents a value.
"""

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .buyer_schemas import RequirementDraft
from .schemas import FieldIssue

# A core field and the severity of its "not found" note. target_price is a soft info note — a buyer
# often has no target price, which is not a problem.
_MISSING: list[tuple[str, str]] = [
    ("title", "warning"),
    ("quantity", "warning"),
    ("target_price", "info"),
    ("needed_by", "info"),
    ("quote_deadline", "info"),
]

_MULTI_MSG = (
    "The document requests several different items. Pick the one this requirement is for "
    "(each item is listed under items); quantities of different items are never combined."
)

# A bare zone word (ET/CT/MT/PT or Eastern/Central/…) names the zone but not whether daylight saving
# is in effect, so it is resolved against the deadline's own date (ET in July -> -04:00, in Jan -> -05:00).
_GENERAL_ZONES = {
    "ET": "America/New_York",
    "EASTERN": "America/New_York",
    "CT": "America/Chicago",
    "CENTRAL": "America/Chicago",
    "MT": "America/Denver",
    "MOUNTAIN": "America/Denver",
    "PT": "America/Los_Angeles",
    "PACIFIC": "America/Los_Angeles",
}
# An explicit standard/daylight abbreviation states the offset itself, so it is honoured exactly as
# printed (the document asserted standard vs daylight).
_FIXED_OFFSETS = {
    "UTC": 0,
    "GMT": 0,
    "Z": 0,
    "ZULU": 0,
    "EST": -5,
    "EDT": -4,
    "CST": -6,
    "CDT": -5,
    "MST": -7,
    "MDT": -6,
    "PST": -8,
    "PDT": -7,
}

# A trailing zone the model may have appended to the value itself (Z, +05:00, -0500, or a letter
# abbreviation): stripped so we work from the bare local wall-clock and trust quote_deadline_tz.
_TRAILING_ZONE = re.compile(r"\s*(Z|[+-]\d{2}:?\d{2}|[A-Za-z]{2,5})$")


def _has_issue(draft: RequirementDraft, field: str, *codes: str) -> bool:
    return any(i.field == field and (not codes or i.code in codes) for i in draft.field_issues)


def _is_empty(value) -> bool:
    return value is None or value == "" or value == []


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    s = value.strip()
    return s or None


def parse_date(value: str | None) -> date | None:
    """The date part of an ISO date or date-time ('Z' or an offset allowed), or None if unparseable."""
    if not value or not str(value).strip():
        return None
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).date()
    except ValueError:
        return None


def is_historical_date(value: str | None, today: date | None = None) -> bool:
    """True for a parseable ISO date/date-time whose local date is strictly before `today`."""
    d = parse_date(value)
    return d is not None and d < (today or date.today())


def _split_local(value: str) -> tuple[str, bool]:
    """Return (bare local 'YYYY-MM-DD[THH:MM[:SS]]', has_time), stripping any zone the model appended."""
    s = _TRAILING_ZONE.sub("", value.strip()).strip()
    return s, ("T" in s and len(s) > 10)


def resolve_quote_deadline(
    value: str | None, tz_label: str | None
) -> tuple[str | None, FieldIssue | None]:
    """Attach the correct UTC offset to the deadline's local wall-clock using the printed zone.

    The local date and clock time are always preserved exactly as the document printed them (so the
    buyer form shows them unshifted). A known zone adds the right offset, daylight-saving aware for a
    bare zone word; an unknown/absent zone on a timed deadline is left naive and flagged for review
    rather than guessed. A date-only deadline is returned unchanged.
    """
    if not value or not str(value).strip():
        return value, None
    local, has_time = _split_local(str(value))
    if not has_time:
        return local, None
    try:
        naive = datetime.fromisoformat(local)
    except ValueError:
        return local, None
    label = (tz_label or "").strip().upper().rstrip(".")
    if label in _FIXED_OFFSETS:
        off = timezone(timedelta(hours=_FIXED_OFFSETS[label]))
        return naive.replace(tzinfo=off).isoformat(), None
    if label in _GENERAL_ZONES:
        return naive.replace(tzinfo=ZoneInfo(_GENERAL_ZONES[label])).isoformat(), None
    issue = FieldIssue(
        field="quote_deadline",
        severity="review",
        code="time_zone_unclear",
        message="The document gives a deadline time but no clear time zone. Confirm the time and set the deadline yourself.",
    )
    return naive.isoformat(), issue


def _distinct_item_names(draft: RequirementDraft) -> list[str]:
    names: list[str] = []
    for it in draft.items:
        name = (it.item_name or "").strip()
        if name and name.lower() not in {n.lower() for n in names}:
            names.append(name)
    return names


def _enforce_single_item(draft: RequirementDraft) -> bool:
    """A requirement is for ONE item. If several distinct items are requested, never combine or pick:
    null the single-item fields and ask the buyer to choose, with ONE message. Returns True if multi.

    Any model-supplied issue on title/quantity/target_price is cleared first, so the buyer never sees
    a "not found" for a field that is deliberately blank pending their choice.
    """
    if len(_distinct_item_names(draft)) < 2:
        return False
    draft.title = None
    draft.quantity = None
    draft.target_price = None
    draft.field_issues = [
        i for i in draft.field_issues if i.field not in ("title", "quantity", "target_price")
    ]
    draft.field_issues.append(
        FieldIssue(field="title", severity="review", code="multiple_items", message=_MULTI_MSG)
    )
    return True


def _flag_historical_dates(draft: RequirementDraft, today: date | None) -> None:
    for field in ("needed_by", "quote_deadline"):
        value = getattr(draft, field)
        if is_historical_date(value, today) and not _has_issue(draft, field, "historical_date"):
            draft.field_issues.append(
                FieldIssue(
                    field=field,
                    severity="review",
                    code="historical_date",
                    message=f"The {field.replace('_', ' ')} ({value}) is in the past. Check the document and set a current date.",
                )
            )


def finalize(draft: RequirementDraft, *, today: date | None = None) -> RequirementDraft:
    """Trim, enforce single-item choice, resolve the deadline zone, flag past dates, note missing fields."""
    draft.title = _blank_to_none(draft.title)
    draft.description = _blank_to_none(draft.description)

    multi = _enforce_single_item(draft)

    resolved, tz_issue = resolve_quote_deadline(draft.quote_deadline, draft.quote_deadline_tz)
    draft.quote_deadline = resolved
    if tz_issue and not _has_issue(draft, "quote_deadline", "time_zone_unclear"):
        draft.field_issues.append(tz_issue)

    _flag_historical_dates(draft, today)

    # When several items need a choice, the single "choose an item" message covers title/quantity/
    # target_price — do not also add a "not found" for those deliberately-blank fields.
    skip = {"title", "quantity", "target_price"} if multi else set()
    for field, severity in _MISSING:
        if field in skip:
            continue
        value = getattr(draft, field)
        if _is_empty(value) and not _has_issue(draft, field):
            draft.field_issues.append(
                FieldIssue(
                    field=field,
                    severity=severity,  # type: ignore[arg-type]
                    code="not_found",
                    message=f"No {field.replace('_', ' ')} found in the document. Check the file or enter it yourself.",
                )
            )
    return draft

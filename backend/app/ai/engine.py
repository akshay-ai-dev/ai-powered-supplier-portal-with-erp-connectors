"""The assistant's conversation engine: IVR-style menus that fill a form one question at a time.

Stateless on the server. The client keeps `state = {flow, values, page, filter}` and sends it back with
each answer. Nothing in it is trusted: option lists are recomputed from the caller's own permissions on
every turn, and before submitting, every stored answer is validated again.

Keys:  digits pick an option on choice screens   0 back   9 more   * cancel   # skip / use the default / confirm
       On free-entry screens (text, numbers, dates) 0 is just the number zero, so type "back" or "cancel" there.
"""

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.ai.flows import FLOWS, Ctx, Flow, Option, Step, flows_for
from app.services.context import channel as channel_var
from app.services.errors import DomainError, Forbidden

PAGE_SIZE = 8
MAX_VALUES = 40
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")
STALE = "This conversation is out of date. Please start again."


# ------------------------------------------------------------------ parsing
def _parse_number(text: str, integer: bool, step: Step) -> int | float:
    t = re.sub(r"[,\s$€£]", "", text)
    try:
        value: int | float = int(t) if integer else float(t)
    except ValueError:
        raise ValueError(
            "Please type a whole number." if integer else "Please type a number, for example 12.50."
        ) from None
    if step.min is not None and value < step.min:
        raise ValueError(f"The smallest allowed value is {step.min:g}.")
    if step.max is not None and value > step.max:
        raise ValueError(f"The largest allowed value is {step.max:g}.")
    return value


def _parse_date(text: str) -> str:
    for fmt in DATE_FORMATS:
        try:
            d = datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
        if d < date.today():
            raise ValueError("That date is in the past.")
        return d.isoformat()
    raise ValueError("Please type a date like 2026-11-30.")


def _parse_datetime(text: str, tz_offset: int) -> str:
    t = text.strip().replace("T", " ")
    for fmt, add in (("%Y-%m-%d %H:%M", False), ("%Y-%m-%d", True)):
        try:
            local = datetime.strptime(t, fmt)
        except ValueError:
            continue
        if add:
            local = local.replace(hour=17)
        utc = (local + timedelta(minutes=tz_offset)).replace(tzinfo=UTC)
        if utc <= datetime.now(UTC):
            raise ValueError("That date and time is in the past.")
        return utc.isoformat(timespec="seconds")
    raise ValueError("Please type a date and time like 2026-11-30 17:00.")


def _show_datetime(iso: str, tz_offset: int) -> str:
    return (datetime.fromisoformat(iso) - timedelta(minutes=tz_offset)).strftime("%Y-%m-%d %H:%M")


# ------------------------------------------------------------------ option lists
def _options(step: Step, ctx: Ctx) -> list[Option]:
    return step.options(ctx) if step.options else []


def _label_for(step: Step, ctx: Ctx, value: Any) -> str:
    if step.kind == "multichoice":
        wanted = set(value or [])
        return ", ".join(o.label for o in _options(step, ctx) if o.value in wanted) or "-"
    if step.kind == "choice":
        return next((o.label for o in _options(step, ctx) if o.value == value), str(value))
    if step.kind == "file":
        return "Attached" if value else "(none)"
    if value is None:
        return "(skipped)"
    if step.kind == "datetime":
        return _show_datetime(value, ctx.tz_offset)
    return str(value)


# ------------------------------------------------------------------ validation of stored answers
def _check_stored(step: Step, value: Any, ctx: Ctx) -> None:
    """Re-validate an answer taken from client-held state. Raises DomainError(STALE) on anything that could not have been entered."""
    bad = DomainError(STALE)
    if step.kind == "choice":
        if value not in [o.value for o in _options(step, ctx)]:
            raise bad
        return
    if step.kind == "multichoice":
        allowed = {o.value for o in _options(step, ctx)}
        if not isinstance(value, list) or not value or any(v not in allowed for v in value):
            raise bad
        return
    if value is None:
        if not step.optional:
            raise bad
        return
    if step.kind == "text":
        if not isinstance(value, str) or not value.strip() or (step.max and len(value) > step.max):
            raise bad
    elif step.kind in ("int", "number"):
        if isinstance(value, bool) or not isinstance(
            value, int if step.kind == "int" else (int, float)
        ):
            raise bad
        if (step.min is not None and value < step.min) or (
            step.max is not None and value > step.max
        ):
            raise bad
    elif step.kind == "date":
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError):
            raise bad from None
    elif step.kind == "datetime":
        try:
            datetime.fromisoformat(value)
        except (TypeError, ValueError):
            raise bad from None
    elif step.kind == "file" and value is not True:
        raise bad


# ------------------------------------------------------------------ rendering
def _menu_response(
    user: dict, message: str = "", error: str | None = None, done: dict | None = None
) -> dict:
    flows = flows_for(user)
    return {
        "stage": "menu",
        "state": None,
        "message": message
        or (
            "What would you like to do?"
            if flows
            else "There are no assistant forms for your role yet."
        ),
        "error": error,
        "options": [
            {"key": str(i + 1), "label": f.title, "description": f.description}
            for i, f in enumerate(flows)
        ],
        "controls": {"back": False, "cancel": False, "skip": False, "more": False, "file": False},
        "result": done,
    }


def _state(flow: Flow, values: dict, page: int = 0, flt: str = "") -> dict:
    return {"flow": flow.id, "values": values, "page": page, "filter": flt}


def _step_response(
    flow: Flow, steps: list[Step], step: Step, ctx: Ctx, state: dict, error: str | None = None
) -> dict:
    answered = sum(1 for s in steps if s.key in ctx.values)
    options: list[dict] = []
    more = False
    if step.kind == "choice":
        chunk, more = paged(_options(step, ctx), state)
        options = [{"key": str(i + 1), "label": o.label} for i, o in enumerate(chunk)]
    elif step.kind == "multichoice":
        options = [{"key": str(i + 1), "label": o.label} for i, o in enumerate(_options(step, ctx))]
    return {
        "stage": "step",
        "state": state,
        "flow": flow.id,
        "title": flow.title,
        "step": step.key,
        "kind": step.kind,
        "message": step.prompt,
        "hint": step.hint,
        "error": error,
        "options": options,
        "filter": state["filter"],
        "controls": {
            "back": True,
            "cancel": True,
            "skip": step.optional or step.default is not None,
            "more": more,
            "file": step.kind == "file",
        },
        "progress": {"done": answered, "total": len(steps)},
        "result": None,
    }


def _summary_response(
    flow: Flow, steps: list[Step], ctx: Ctx, state: dict, error: str | None = None
) -> dict:
    return {
        "stage": "summary",
        "state": state,
        "flow": flow.id,
        "title": flow.title,
        "message": "Please check your answers.",
        "warning": flow.warning,
        "error": error,
        "summary": [
            {"label": s.label, "value": _label_for(s, ctx, ctx.values[s.key])}
            for s in steps
            if s.key in ctx.values
        ],
        "options": [],
        "controls": {
            "back": True,
            "cancel": True,
            "skip": False,
            "more": False,
            "file": False,
            "confirm": True,
        },
        "progress": {"done": len(steps), "total": len(steps)},
        "result": None,
    }


# ------------------------------------------------------------------ the turn
def menu(user: dict) -> dict:
    return _menu_response(user)


def _clean_state(state: dict) -> tuple[Flow, dict]:
    flow = FLOWS.get(state.get("flow"))
    values = state.get("values")
    if (
        flow is None
        or not isinstance(values, dict)
        or len(values) > MAX_VALUES
        or not all(isinstance(k, str) and len(k) < 80 for k in values)
    ):
        raise DomainError(STALE)
    page, flt = state.get("page", 0), state.get("filter", "")
    if not isinstance(page, int) or page < 0 or not isinstance(flt, str) or len(flt) > 100:
        raise DomainError(STALE)
    return flow, _state(flow, dict(values), page, flt)


def advance(conn, user: dict, state: dict | None, text: str | None, tz_offset: int = 0) -> dict:
    """One conversation turn. Returns the next screen: menu, a question, the summary, or the result."""
    text = (text or "").strip()
    if not state or not state.get("flow"):
        return _start(user, text, conn, tz_offset)

    flow, st = _clean_state(state)
    if user["role"] not in flow.roles:
        raise Forbidden("This form is not available for your role")
    ctx = Ctx(conn, user, st["values"], tz_offset)
    steps = flow.steps(ctx)
    current = next((s for s in steps if s.key not in ctx.values), None)
    lowered = text.lower()

    if lowered in ("*", "cancel"):
        return _menu_response(user, "Cancelled. Nothing was saved. What would you like to do?")

    if current is None:  # summary screen (a look-up has none, so it just answers)
        if flow.readonly:
            return _submit(flow, steps, ctx, st)
        return _on_summary(flow, steps, ctx, st, text, lowered)

    if not text:
        return _step_response(flow, steps, current, ctx, st)

    is_choice = current.kind in ("choice", "multichoice")
    if lowered == "back" or (is_choice and text == "0"):
        return _go_back(user, flow, ctx, st)

    try:
        if current.kind == "choice":
            return _answer_choice(flow, steps, current, ctx, st, text, lowered)
        value = _answer_free(current, ctx, text, lowered)
    except ValueError as exc:
        return _step_response(flow, steps, current, ctx, st, error=str(exc))
    return _store(flow, ctx, st, current, value)


def _start(user: dict, text: str, conn, tz_offset: int) -> dict:
    flows = flows_for(user)
    if not text:
        return _menu_response(user)
    if text.isdigit() and 1 <= int(text) <= len(flows):
        flow = flows[int(text) - 1]
        return _enter(flow, Ctx(conn, user, {}, tz_offset), _state(flow, {}))
    return _menu_response(user, error="Please choose one of the numbers below.")


def _enter(flow: Flow, ctx: Ctx, st: dict) -> dict:
    steps = flow.steps(ctx)
    current = next((s for s in steps if s.key not in ctx.values), None)
    if current is None:
        if flow.readonly:  # a look-up has nothing to confirm: show the answer
            return _submit(flow, steps, ctx, st)
        return _summary_response(flow, steps, ctx, st)
    if current.kind in ("choice", "multichoice") and not _options(current, ctx):
        return _menu_response(ctx.user, current.empty + " What else can I help with?")
    return _step_response(flow, steps, current, ctx, st)


def _go_back(user: dict, flow: Flow, ctx: Ctx, st: dict) -> dict:
    if not ctx.values:
        return _menu_response(user)
    ctx.values.pop(next(reversed(ctx.values)))
    st["page"], st["filter"] = 0, ""
    return _enter(flow, ctx, st)


def paged(options: list[Option], st: dict) -> tuple[list[Option], bool]:
    """The options shown on the current page (after the search filter), and whether there is more than one page."""
    visible = [o for o in options if not st["filter"] or st["filter"].lower() in o.label.lower()]
    pages = max((len(visible) + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    st["page"] = st["page"] % pages
    return visible[st["page"] * PAGE_SIZE : (st["page"] + 1) * PAGE_SIZE], pages > 1


def pick_from(options: list[Option], st: dict, text: str) -> tuple[bool, Any, str | None]:
    """Interpret an answer on a numbered list: (True, value, None) when an option was chosen, otherwise
    (False, None, error) and the caller shows the list again (st holds the page and search filter)."""
    if text.lower() == "all" and st["filter"]:
        st["filter"], st["page"] = "", 0
        return False, None, None
    if text.isdigit():
        n = int(text)
        chunk, more = paged(options, st)
        if n == 9 and more:
            st["page"] += 1
            return False, None, None
        if 1 <= n <= len(chunk):
            return True, chunk[n - 1].value, None
        return False, None, "Please choose one of the numbers shown."
    # anything else narrows the list ("search")
    st["filter"], st["page"] = text[:100], 0
    if not paged(options, st)[0]:
        st["filter"] = ""
        return False, None, "Nothing matches that. Showing everything again."
    return False, None, None


def _answer_choice(flow, steps, step, ctx, st, text, lowered) -> dict:
    chosen, value, error = pick_from(_options(step, ctx), st, text)
    if chosen:
        return _store(flow, ctx, st, step, value)
    return _step_response(flow, steps, step, ctx, st, error=error)


def _answer_free(step: Step, ctx: Ctx, text: str, lowered: str) -> Any:
    skipping = text == "#" or lowered == "skip"
    if skipping:
        if step.default is not None:
            return step.default
        if step.optional:
            return None
        raise ValueError("This question needs an answer.")
    if step.kind == "multichoice":
        opts = _options(step, ctx)
        if lowered == "all":
            return [o.value for o in opts]
        try:
            picks = sorted({int(p) for p in re.split(r"[,\s]+", text) if p})
        except ValueError:
            raise ValueError(
                "Type the numbers separated by commas, for example 1,3, or all."
            ) from None
        if not picks or any(not 1 <= p <= len(opts) for p in picks):
            raise ValueError("Please choose from the numbers shown.")
        return [opts[p - 1].value for p in picks]
    if step.kind == "text":
        if step.max and len(text) > step.max:
            raise ValueError(f"Please keep it under {int(step.max)} characters.")
        if step.key == "tracking_no":
            if re.fullmatch(r"[A-Za-z0-9_-]+", text) is None:
                raise ValueError("Use only letters, numbers, hyphens, and underscores.")
            return text.upper()
        return text
    if step.kind in ("int", "number"):
        return _parse_number(text, step.kind == "int", step)
    if step.kind == "date":
        return _parse_date(text)
    if step.kind == "datetime":
        return _parse_datetime(text, ctx.tz_offset)
    if step.kind == "file":
        if lowered in ("attached", "yes"):
            return True
        raise ValueError("Choose a file with the button, or type # to skip.")
    raise ValueError("Unsupported question.")


def _store(flow: Flow, ctx: Ctx, st: dict, step: Step, value: Any) -> dict:
    ctx.values[step.key] = value
    st["page"], st["filter"] = 0, ""
    return _enter(flow, ctx, st)


def _on_summary(flow, steps, ctx, st, text, lowered) -> dict:
    if lowered in ("back",) or text == "0":
        return _go_back(ctx.user, flow, ctx, st)
    if text != "#" and lowered not in ("confirm", "yes", "ok"):
        return _summary_response(
            flow,
            steps,
            ctx,
            st,
            error="Press Confirm (or type #) to submit, 0 to go back, * to cancel.",
        )
    return _submit(flow, steps, ctx, st)


def _submit(flow: Flow, steps: list[Step], ctx: Ctx, st: dict) -> dict:
    for step in steps:  # trust nothing that came from the client
        _check_stored(step, ctx.values.get(step.key), ctx)
    token = channel_var.set("assistant")
    try:
        result = flow.submit(ctx)
    except DomainError as exc:
        ctx.conn.rollback()
        if flow.readonly:  # nothing to go back and fix on a look-up
            return _menu_response(ctx.user, error=exc.message)
        return _summary_response(flow, steps, ctx, st, error=exc.message)
    finally:
        channel_var.reset(token)
    return _menu_response(ctx.user, "Done. Anything else?", done=result)

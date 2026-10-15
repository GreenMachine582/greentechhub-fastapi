"""lenient — query-string values for a page's own filters, read leniently:
a missing, blank or unreadable value gives the default instead of a 422, so a
hand-edited or stale URL still renders the page.

    on = optional_date(request.query_params.get("on"), default=date.today())
    method = optional_choice(request.query_params.get("method"), CostMethod, CostMethod.AVERAGE)

For an API, where a bad value should be an error, use FastAPI's own typed
parameters instead.
"""

from collections.abc import Iterable
from datetime import UTC, date, datetime
from enum import Enum
from typing import overload


def _clean(raw: str | None) -> str:
    return (raw or "").strip()


def optional_date[D: date | None](raw: str | None, default: D = None) -> date | D:
    """An ISO date ("2025-07-01"), else `default`."""
    try:
        return date.fromisoformat(value) if (value := _clean(raw)) else default
    except ValueError:
        return default


def optional_datetime[D: datetime | None](raw: str | None, default: D = None) -> datetime | D:
    """An ISO datetime, UTC when it has no offset, else `default`."""
    try:
        parsed = datetime.fromisoformat(value) if (value := _clean(raw)) else None
    except ValueError:
        return default
    if parsed is None:
        return default
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def optional_int[D: int | None](raw: str | None, default: D = None) -> int | D:
    """A whole number (a leading "-" allowed), else `default`."""
    try:
        return int(value) if (value := _clean(raw)) else default
    except ValueError:
        return default


@overload
def optional_choice[E: Enum](raw: str | None, choices: type[E], default: E) -> E: ...
@overload
def optional_choice[D](raw: str | None, choices: Iterable[str], default: D) -> str | D: ...
def optional_choice(raw, choices, default):
    """One of `choices`, else `default`. `choices` is an Enum class (its
    values, giving the member) or an iterable of allowed strings."""
    value = _clean(raw)
    if not value:
        return default
    if isinstance(choices, type) and issubclass(choices, Enum):
        try:
            return choices(value)
        except ValueError:
            return default
    return value if value in set(choices) else default

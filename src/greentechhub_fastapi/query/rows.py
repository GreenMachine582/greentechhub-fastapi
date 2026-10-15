"""rows — get_owned_or_404: one row by primary key, or a 404, optionally
scoped to an owner.

    stock = await get_owned_or_404(session, Stock, stock_id)
    txn = await get_owned_or_404(session, Transaction, txn_id, owner=identity.subject)

Someone else's row is a 404, not a 403, so a guessed id can't tell "exists
but isn't yours" from "doesn't exist". The HTTPException becomes
register_error_pages' 404 page, register_api_error_handlers' not_found
envelope under the API prefix, or FastAPI's default.

`session` is any SQLAlchemy (or SQLModel) AsyncSession: one `session.get`,
so this package needs no SQLAlchemy import of its own.
"""

from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException


async def get_owned_or_404[T](
    session: Any,
    model: type[T],
    id: Any,
    *,
    owner: Any = None,
    owner_field: str = "user_id",
    detail: str | None = None,
    options: Sequence[Any] = (),
) -> T:
    """The `model` row with primary key `id` (a tuple for a composite key).

    With `owner`, a row whose `owner_field` isn't `owner` counts as missing.
    `options` are loader options for `session.get`, e.g.
    `[selectinload(Transaction.stock)]` for a relationship the route reads,
    which can't be lazy-loaded under an AsyncSession. They apply when the row
    is loaded, as with `session.get` itself: a row the session already holds
    comes back as it is.
    Raises HTTPException(404, detail or "<Model> not found"), and
    AttributeError when `owner` is given but `model` has no `owner_field`.
    """
    if owner is not None and not hasattr(model, owner_field):
        raise AttributeError(f"{model.__name__} has no owner field {owner_field!r}")
    row = await session.get(model, id, options=list(options) or None)
    if row is None or (owner is not None and getattr(row, owner_field) != owner):
        raise HTTPException(status_code=404, detail=detail or f"{model.__name__} not found")
    return row

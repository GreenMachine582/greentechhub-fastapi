"""register_api_tokens — puts greentechhub-core's ApiTokenStore on the app,
so register_auth(..., bearer=True) also signs in personal API tokens and
ApiTokenViews can manage them (greentechhub_fastapi.api_tokens).

A database-backed store is core's SQLAlchemyApiTokenStore over
gth_api_tokens; InMemoryApiTokenStore suits tests.
"""

from typing import Any

from fastapi import FastAPI
from greentechhub_core.security import ApiTokenStore

from greentechhub_fastapi.auth.personal_tokens import API_TOKENS_STATE_KEY


def register_api_tokens(
    app: FastAPI, settings: Any = None, *, store: ApiTokenStore
) -> ApiTokenStore:
    """Install the app's ApiTokenStore and return it. `settings` is accepted
    for symmetry with the other register_* calls."""
    if app.middleware_stack is not None:
        raise RuntimeError("register_api_tokens must run before the app starts")
    setattr(app.state, API_TOKENS_STATE_KEY, store)
    return store

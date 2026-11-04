"""single_user — the AUTH_ADAPTER=single_user adapter: a local app with one
person and no sign-in. Every request resolves to the same fixed Identity, so
everything that acts "for the signed-in user" (notifications, settings, the
audit actor, require_page_identity) works without a login page.

The identity comes from settings, each read tolerantly like AUTH_ADAPTER:
  - SINGLE_USER_SUBJECT (default "local"): its subject, the key notifications
    and settings are stored under. Keep it stable.
  - SINGLE_USER_NAME (default "Local user"): its display name and username.
  - SINGLE_USER_GROUPS (default none): its groups, so ROLE_GROUPS can grant it
    roles when register_permissions is in use.

There is no authentication at all: anyone who can reach the app is that
person. Use it only for an app bound to localhost (or otherwise reachable by
its one user alone).
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from greentechhub_core.identity import Identity

from greentechhub_fastapi.registration._settings import read_list_setting, read_str_setting

logger = logging.getLogger(__name__)

SINGLE_USER_STATE_KEY = "gth_single_user"
SINGLE_USER_PROVIDER = "single_user"


def build_single_user_identity(settings: Any) -> Identity:
    """The fixed Identity SINGLE_USER_* describe."""
    subject = read_str_setting(settings, "SINGLE_USER_SUBJECT", "local")
    name = read_str_setting(settings, "SINGLE_USER_NAME", "Local user")
    groups = read_list_setting(settings, "SINGLE_USER_GROUPS")
    return Identity(subject=subject, username=name, email=None, groups=groups,
                    claims={}, display_name=name, provider=SINGLE_USER_PROVIDER)


def build_single_user_get_current_user(
    identity: Identity,
) -> Callable[[Request], Awaitable[Identity | None]]:
    """A get_current_user that always answers `identity`."""

    async def _get_current_user(request: Request) -> Identity | None:
        return identity

    return _get_current_user


def single_user_identity(app: Any) -> Identity | None:
    """The app's single user when register_auth set AUTH_ADAPTER=single_user,
    else None — for code with no request (a background job, a scheduled
    task) that needs to act for that person."""
    return getattr(app.state, SINGLE_USER_STATE_KEY, None)

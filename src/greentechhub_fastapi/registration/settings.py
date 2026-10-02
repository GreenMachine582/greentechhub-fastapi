"""register_settings — puts greentechhub-core's Settings on the app, and
optionally mounts the settings page.

Opt-in like every register_* call. It:
  - builds core's Settings(registry, store, cipher=cipher) — a malformed
    env override (SETTING_UI__PAGE_SIZE=lots), or a secret setting without
    a cipher, fails here, at startup;
  - adds SettingsContextMiddleware innermost, so page requests carry the
    user, granted permissions and effective settings for
    settings.settings_context (the Jinja2Templates context processor);
  - mounts `views` (a SettingsViews) when given, which also turns on the
    user menu's Settings link and the theme toggle's server save.

`manage_permission` gates the App section and its save; it needs
register_permissions to have run first (a bootstrap admin from
ROLE_BOOTSTRAP is enough — no Authentik required). The service supplies
the permission: none is defined here.
"""

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI
from greentechhub_core.permissions import Permission
from greentechhub_core.settings import SecretCipher, Settings, SettingsRegistry, SettingsStore
from starlette.middleware import Middleware

from greentechhub_fastapi.permissions import RESOLVER_STATE_KEY
from greentechhub_fastapi.settings import (
    SETTINGS_STATE_KEY,
    SettingsConfig,
    SettingsContextMiddleware,
    SettingsViews,
)


def register_settings(
    app: FastAPI,
    settings: Any,
    *,
    registry: SettingsRegistry,
    store: SettingsStore,
    views: SettingsViews | None = None,
    manage_permission: str | None = None,
    logout_url: str | None = None,
    env: Mapping[str, Any] | None = None,
    cipher: SecretCipher | None = None,
) -> Settings:
    """Install the app's Settings and return it (a sync tool or a route can
    share it). `settings` is the service's GTHBaseSettings, accepted for
    symmetry with the other register_* calls; values come from `registry`
    and `store`. `logout_url` is offered to greentechhub-ui's user menu
    (e.g. LoginViews' "/logout"). `cipher` (e.g. core's
    settings.crypto.FernetCipher) encrypts the registry's secret settings;
    it's required when there are any."""
    if app.middleware_stack is not None:
        raise RuntimeError("register_settings must run before the app starts")
    permission = Permission(manage_permission) if manage_permission is not None else None
    if permission is not None and getattr(app.state, RESOLVER_STATE_KEY, None) is None:
        raise RuntimeError("manage_permission needs register_permissions(app, ...) first")
    service = Settings(registry, store, env=env, cipher=cipher)
    setattr(
        app.state,
        SETTINGS_STATE_KEY,
        SettingsConfig(
            settings=service,
            manage_permission=permission,
            logout_url=logout_url,
            url=views.url if views is not None else None,
        ),
    )
    # Appended, not add_middleware (which prepends): the last entry is the
    # innermost, so proxy headers and forward-auth state are already set.
    app.user_middleware.append(Middleware(SettingsContextMiddleware))
    if views is not None:
        app.include_router(views.router())
    return service

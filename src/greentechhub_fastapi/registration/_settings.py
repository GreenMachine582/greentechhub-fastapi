"""setting_value / read_list_setting / read_str_setting — tolerant, private
helpers for reading the adapter settings (AUTH_ADAPTER, CORS_ALLOWED_ORIGINS,
TRUSTED_PROXIES, ROLE_GROUPS, ROLE_BOOTSTRAP).

greentechhub_core's GTHBaseSettings declares them as lowercase fields
(`trusted_proxies`, …) since core v0.12, so a service gets them just by
extending it. A service's own SCREAMING_CASE attribute, declared or set at
runtime (PyFinBot sets CORS_ALLOWED_ORIGINS="*" in development), comes
first when it's non-empty; otherwise core's lowercase field. Both read the
same env var, so they only differ when a service changed one at runtime,
and core's non-empty defaults (auth_adapter="local") mustn't hide that. A
plain object without GTHBaseSettings works too.

Accepts either a comma-separated string (the natural shape for an env-var-backed
field, e.g. CORS_ALLOWED_ORIGINS="https://a.example,https://b.example") or an
already-parsed list/tuple (a service that declared the field as list[str] in
pydantic-settings, which supports that natively). Missing/falsy defaults to an
empty list — "safe out of the box" per docs/registration.md, not "misconfigured
crash".
"""

from collections.abc import Sequence
from typing import Any


def setting_value(settings: Any, name: str) -> Any:
    """`name` (e.g. "TRUSTED_PROXIES") from `settings`: the service's own
    SCREAMING_CASE attribute when it's non-empty, else the lowercase field
    GTHBaseSettings declares; None if neither is set."""
    for attribute in (name.upper(), name.lower()):
        if value := getattr(settings, attribute, None):
            return value
    return None


def read_list_setting(settings: Any, name: str) -> list[str]:
    value = setting_value(settings, name)
    if not value:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, Sequence):
        return [str(item) for item in value]
    return []


def read_str_setting(settings: Any, name: str, default: str) -> str:
    """Read a scalar string setting, falling back to `default` when unset/falsy."""
    value = setting_value(settings, name)
    if not value:
        return default
    return str(value)

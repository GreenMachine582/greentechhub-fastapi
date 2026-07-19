"""read_list_setting / read_str_setting — tolerant, private helpers for reading
settings (CORS_ALLOWED_ORIGINS, TRUSTED_PROXIES, AUTH_ADAPTER) that live on a
service's own Settings subclass, not on greentechhub_core.config.GTHBaseSettings
itself (it only declares secret_key/log_level).

Accepts either a comma-separated string (the natural shape for an env-var-backed
field, e.g. CORS_ALLOWED_ORIGINS="https://a.example,https://b.example") or an
already-parsed list/tuple (a service that declared the field as list[str] in
pydantic-settings, which supports that natively). Missing/falsy defaults to an
empty list — "safe out of the box" per docs/registration.md, not "misconfigured
crash".
"""

from collections.abc import Sequence
from typing import Any


def read_list_setting(settings: Any, name: str) -> list[str]:
    value = getattr(settings, name, "")
    if not value:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, Sequence):
        return [str(item) for item in value]
    return []


def read_str_setting(settings: Any, name: str, default: str) -> str:
    """Read a scalar string setting, falling back to `default` when unset/falsy."""
    value = getattr(settings, name, "")
    if not value:
        return default
    return str(value)

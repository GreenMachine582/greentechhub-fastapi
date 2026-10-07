"""setting_value / read_list_setting / read_str_setting — the readers for the
adapter settings (AUTH_ADAPTER, CORS_ALLOWED_ORIGINS, TRUSTED_PROXIES,
ROLE_GROUPS, ROLE_BOOTSTRAP) the register_* functions use.

They are greentechhub-core's (`greentechhub_core.config`, core v0.13), so
every adapter reads them the same way: a service's own SCREAMING_CASE
attribute first when it's non-empty, else GTHBaseSettings' lowercase
field. Re-exported here so existing imports keep working.
"""

from greentechhub_core.config import read_list_setting, read_str_setting, setting_value

__all__ = ["read_list_setting", "read_str_setting", "setting_value"]

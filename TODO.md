[← Back to README](README.md)

# ✅ TODO / Milestones

> Open work only: remove an item when it ships — its release note lands in CHANGELOG.md automatically (release-please). See [README.md](README.md) for context and [docs/](docs/) for the detailed design behind each item.

> Shipped work is recorded in [CHANGELOG.md](CHANGELOG.md) and on the [Releases page](https://github.com/GreenMachine582/greentechhub-fastapi/releases) — this file only tracks what's still open.

## 🗺️ Milestones

### Settings & permissions
Shipped: #5 (`register_permissions`), #9 (`register_settings`, `SettingsViews`), #11 (`RoleAdminViews`), #20
(secret settings: `cipher=`, write-only saves, `get_secret`) and #21 (the landing-page redirect after login, acting
on core #14's setting). Nothing here is open; releases next: ui v0.13.0 and fastapi v0.10.0 (core v0.8.0 is out).

### From the PyFinBot review
Generic pieces PyFinBot built for itself, to move here (opt-in) so it can delete them:
- [ ] `LoginViews.login_template` defaults to greentechhub-ui's `login_page.html` (after ui ships it); apps can
  still override it
- [ ] `register_api_error_handlers(app, prefix="/api")` — the `{code, message, details}` envelope for
  `HTTPException` (OAuth2's 401, unknown routes, 405) and request validation errors under the prefix, plus
  `UnauthorizedError` with `WWW-Authenticate: Bearer` and core's explicit-status error (core TODO); everything else
  keeps FastAPI's defaults. From PyFinBot's `web/api_errors.py`
- [ ] An opt-in admin site banner — core's setting definitions (message + tone) registered with
  `register_settings`, plus a context processor that turns them into greentechhub-ui's `site_banners`. From
  PyFinBot's `site_banners_context`

### v1.0 — Validated in production
- [ ] BottleBot's retrofit fully on it
- [ ] PyFinBot's greenfield build fully on it

## 🔄 Migration Tracking

### BottleBot
- [ ] Adopt `register_auth`, if/when BottleBot grows a login (lowest priority)
- [ ] Adopt `register_permissions`/`register_settings` alongside `register_auth` (same trigger, lowest priority)
- [ ] Replace watchlist's `_watchlist_page_params`/`_next_url` with `query.page_params`/`query.next_page_url` (v0.7)

### PyFinBot
- [ ] Register everything from `greentechhub-fastapi` from the start (greenfield)
- [ ] Adopt `register_permissions` + `register_settings` (with core's `USER_PREFERENCES` and `[sqlalchemy]` stores, `SettingsViews` and the `settings_context` processor) and `RoleAdminViews` over a SQLAlchemy `GrantStore` — all have shipped
- [ ] Follow-up pass on the PyFinBot web interface brief — it currently references `greentechhub-core`'s auth adapter directly rather than this package

### Market Watch (planned)
- [ ] Not started — builds on this from day one, same as PyFinBot

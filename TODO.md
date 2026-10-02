[← Back to README](README.md)

# ✅ TODO / Milestones

> Open work only: remove an item when it ships — its release note lands in CHANGELOG.md automatically (release-please). See [README.md](README.md) for context and [docs/](docs/) for the detailed design behind each item.

> Shipped work is recorded in [CHANGELOG.md](CHANGELOG.md) and on the [Releases page](https://github.com/GreenMachine582/greentechhub-fastapi/releases) — this file only tracks what's still open.

## 🗺️ Milestones

### Settings & permissions
Shipped: #5 (`register_permissions`), #9 (`register_settings`, `SettingsViews`) and #11 (`RoleAdminViews`). Open:
#20 (secret settings) and #21 (the landing-page redirect, acting on core #14's setting), below.

#### Secret settings
Settings whose value is a credential (an email app password, an API token) can't be plain settings: stores keep JSON
as-is, `effective()` returns values to templates, and `SettingsViews` echoes a `str` back into the form. These items
add an opt-in **secret** kind across the three packages. Order across repos: core #18 → ui #19 → fastapi #20, then
releases core v0.8.0, ui v0.13.0 and fastapi v0.10.0 (core v0.8.0 is out and pinned). The first consumer is
PyFinBot's per-user email account for Commsec sync (its app password), registered in PyFinBot's `todo.md`.
- [ ] **#20 `feat(settings): secret settings in SettingsViews`**
  - `register_settings(..., cipher=None)` passes the cipher to core's `Settings`.
  - On save, a blank secret field keeps the stored value, and the `<key>.__clear` box resets it.
  - Secrets never reach `user_settings`, the section's `values` or any template context. Only the marker does.
  - A `get_secret` dependency helper for routes that need the plaintext.
  - Tests: no plaintext in any rendered HTML; blank keeps, clear resets; a wrong or missing cipher fails at startup.
  - Docs: `docs/registration.md` (Settings).

#### Landing page
Core #14 shipped `landing_page_setting` and `LANDING_PAGE_KEY` (`ui.landing_page`): a per-user choice of the service's
own pages. Nothing acts on it yet. Core v0.8.0, pinned here, carries it.
- [ ] **#21 `feat(settings): send users to their landing page after login`**
  - When `register_settings` is on and the registry has core's `LANDING_PAGE_KEY`, `LoginViews` redirects a
    successful login to the user's `ui.landing_page` instead of `redirect_url`. Without either, `redirect_url` is
    unchanged (opt-in).
  - `landing_url(request, identity, *, fallback="/")`, sync and async, returns the resolved page, for a service's own
    routes (e.g. a `/` that isn't itself one of the choices).
  - The value is always one of the setting's choices (core validates it), so it isn't an open redirect. `/` is never
    redirected automatically, since "/" may itself be a choice and would loop.
  - Tests: login lands on the chosen page; the default when unset; `redirect_url` without the setting or without
    `register_settings`; a stale stored page falls back to the default; an HTMX login gets `HX-Redirect` to the same
    URL.
  - Docs: `docs/registration.md` (Settings and LoginViews).

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

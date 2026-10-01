[← Back to README](README.md)

# ✅ TODO / Milestones

> Open work only: remove an item when it ships — its release note lands in CHANGELOG.md automatically (release-please). See [README.md](README.md) for context and [docs/](docs/) for the detailed design behind each item.

> Shipped work is recorded in [CHANGELOG.md](CHANGELOG.md) and on the [Releases page](https://github.com/GreenMachine582/greentechhub-fastapi/releases) — this file only tracks what's still open.

## 🗺️ Milestones

### Settings & permissions
Thin wiring over `greentechhub-core`'s settings and role resolution (design:
[core docs/settings.md](https://github.com/GreenMachine582/greentechhub-core/blob/dev/docs/settings.md)). Every item
is opt-in: nothing runs until the service calls the `register_*` function or mounts the views. Everything works with
`AUTH_ADAPTER=local`, with no Authentik needed. Each PR updates any doc it would otherwise contradict. The numbers are
the cross-repo order: core #1–#4, fastapi #5 (`register_permissions`) and #9 (`register_settings`,
`SettingsViews`) have shipped.
- [ ] **#11 `feat(permissions): role assignment admin page`**
  - `RoleAdminViews(..., permission=...)` over a `GrantStore`, gated on a permission the service supplies.
  - Lists assignments with `gth_data_table`; assigns and revokes with `gth_multiselect`/`gth_confirm_delete`.
  - A `local`-adapter test.

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
- [ ] Adopt `register_permissions` + `register_settings` (with core's `USER_PREFERENCES` and `[sqlalchemy]` stores, `SettingsViews` and the `settings_context` processor) — both have shipped
- [ ] Follow-up pass on the PyFinBot web interface brief — it currently references `greentechhub-core`'s auth adapter directly rather than this package

### Market Watch (planned)
- [ ] Not started — builds on this from day one, same as PyFinBot

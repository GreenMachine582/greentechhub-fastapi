[← Back to README](README.md)

# ✅ TODO / Milestones

> Open work only: remove an item when it ships — its release note lands in CHANGELOG.md automatically (release-please). See [README.md](README.md) for context and [docs/](docs/) for the detailed design behind each item.

> Shipped work is recorded in [CHANGELOG.md](CHANGELOG.md) and on the [Releases page](https://github.com/GreenMachine582/greentechhub-fastapi/releases) — this file only tracks what's still open.

## 🗺️ Milestones

### Settings & permissions
Thin wiring over `greentechhub-core`'s planned settings and role resolution (design:
[core docs/settings.md](https://github.com/GreenMachine582/greentechhub-core/blob/dev/docs/settings.md)). Every item
is opt-in: nothing runs until the service calls the `register_*` function or mounts the views. Everything works with
`AUTH_ADAPTER=local`, with no Authentik needed. Each PR updates any doc it would otherwise contradict. The numbers are
the cross-repo order: core #1–#4 come first.
- [ ] **#5 `feat(permissions): register_permissions and require_permission`**
  - `register_permissions(app, settings, *, resolver=None)` builds a default resolver from the optional
    `ROLE_GROUPS` and `ROLE_BOOTSTRAP` settings.
  - `get_granted_permissions` dependency.
  - `require_permission(p)` (JSON 403) and `require_page_permission(p)`.
  - A `local`-adapter test: the bootstrap subject is allowed, a normal user gets 403.
  - Docs: replace the "RBAC deferred" docstring in `dependencies/identity.py`, plus the README and
    `docs/registration.md` rows.
- [ ] **#9 `feat(settings): register_settings and SettingsViews`**
  - `register_settings(app, settings, *, registry, store, manage_permission=None)`.
  - `get_settings_service`/`get_effective_settings` dependencies.
  - A context processor providing `theme_mode`, `granted` and `user_settings`.
  - `SettingsViews` (in the style of `LoginViews`):
    - `GET /settings` shows a Preferences tab, plus an App tab only when `manage_permission` is set and granted.
    - A POST per section returns 422 with field errors, or a toast.
    - `POST /settings/theme` is the endpoint the theme toggle saves to.
  - A `local`-adapter test of the App tab gating.
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
- [ ] Adopt `register_permissions` + `register_settings` (with core's `USER_PREFERENCES` and `[sqlalchemy]` stores) once #5/#9 ship
- [ ] Follow-up pass on the PyFinBot web interface brief — it currently references `greentechhub-core`'s auth adapter directly rather than this package

### Market Watch (planned)
- [ ] Not started — builds on this from day one, same as PyFinBot

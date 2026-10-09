[← Back to README](README.md)

# ✅ TODO / Milestones

> Open work only: remove an item when it ships — its release note lands in CHANGELOG.md automatically (release-please). See [README.md](README.md) for context and [docs/](docs/) for the detailed design behind each item.

> Shipped work is recorded in [CHANGELOG.md](CHANGELOG.md) and on the [Releases page](https://github.com/GreenMachine582/greentechhub-fastapi/releases) — this file only tracks what's still open.

How work lands: a gap a service hits is fixed in core first when it's framework-free, then here, then in
greentechhub-ui. Releases go in that order and the services bump their pins last. Develop across the repos with
local GTH mode (`scripts/use-local-gth.sh`, see [CONTRIBUTING.md](CONTRIBUTING.md)).

## 🗺️ Milestones

Cross-repo order (with greentechhub-core and greentechhub-ui): Accounts (M1) → Notifications & email (M2) →
consumers live (M3) → ui breaking release (M4) → display & data (M5) → v1.0.

### M1 Accounts — done
Sign-in pages (`LoginViews`, v0.6/v0.11), sign-up (`RegisterViews`, v0.12), password reset and email verification
(v0.12), profile and change password in Settings (v0.12–v0.13), login throttling (v0.12) and throttled API logins
(`throttled_login`, v0.14), opt-in CSRF on the auth forms (v0.13).

### M2 Notifications & email — done
`register_notifications` and `notify` (v0.12), `register_email` and notify-by-email (v0.12), the navbar bell pointed
at the notification centre with no service code (v0.14).

### M3 Consumers live — in progress
- PyFinBot runs on this package throughout. Left on its side: the `forward_auth` switch once Authentik is live. This
  package is ready for it (`register_core` + `TRUSTED_PROXIES`); validating Authentik's JWT is core's TODO.
- BottleBot (lowest priority; it has no login yet):
  - [ ] Adopt `register_auth`, if/when BottleBot grows a login
  - [ ] Adopt `register_permissions`/`register_settings` alongside `register_auth` (same trigger)
  - [ ] Replace watchlist's `_watchlist_page_params`/`_next_url` with `query.page_params`/`query.next_page_url`
    (v0.7)

### M4 ui breaking release — owned by greentechhub-ui
ui drops its CDN-URL defaults, so services must mount `greentechhub_ui.static_dirs()`. This package's share:
- [ ] When it lands, check `mount_static_dirs` in docs/registration.md and the README example still match what ui
  requires, and that the playground mounts them.

### M5 Display & data — next
Shipped ahead of it: core-validated JSON filters (`validated_filter_json`, v0.12) for ui's planned query builder.

- [ ] 1. `feat(auth): CSRF for htmx forms`
  - **Why:** the auth forms are covered (v0.13), but docs/auth.md lists what isn't: `POST /logout`,
    `SettingsViews`, `RoleAdminViews` and a service's own htmx forms. These are the state-changing requests a
    signed-in user makes all day.
  - **Scope:**
    - one token per browser, reusing the `gth_csrf` double-submit cookie;
    - a `csrf_header_context` the page context exposes, so greentechhub-ui's app shell can put it in `hx-headers`
      (`X-CSRF-Token`) and a hidden field on its logout form;
    - a `require_csrf` dependency for POST/PUT/PATCH/DELETE page routes, answering 403 like the auth forms;
    - opt-in on `register_settings` / `RoleAdminViews` / the logout route.
  - **Needs:** a greentechhub-ui change to the app shell, planned with it. core already has `generate_token` and
    `constant_time_compare`.
  - **Done when:** a signed-in page's htmx POST without the header is refused, with it succeeds, and logout works
    from the navbar.
- [ ] 3. `feat(testing): HTTP test fixtures`
  - **Why:** PyFinBot's `tests/conftest.py` hand-rolls what every service on this package needs. This package's own
    tests repeat the HX-Trigger parsing. Core's `greentechhub_core.testing.sqlalchemy` (greentechhub-core#70)
    covers the database half.
  - **Scope:**
    - a `[testing]` extra and an opt-in plugin on top of core's;
    - a client fixture with the session dependency and `Database` pointed at the test connection;
    - auth re-registered after `dependency_overrides.clear()`;
    - `post_login` (the CSRF double-submit), `web_login` (re-setting the Secure session cookie over http),
      `hx_triggers`, and `client_as(persona)`.
  - **Done when:** PyFinBot's `conftest.py` is its own fixtures only.

### Ideas — not scheduled
Each follows the settings/roles pattern: a core model or protocol, a `*Views` class here, a greentechhub-ui template,
one `register_*` call. Who wants it is noted where known.
- `register_admin(app)` — an "Admin" nav group collecting the admin views (roles, audit, users), gated through nav
  permissions
- Users admin — list, search, disable, force a password reset, assign roles inline (builds on `RoleAdminViews`
  and `RegisterViews`)
- System status page — core health checks as a page (status, last checked, response time), admin-only with an
  optional public summary
- Feature flags page — see and toggle flags per app, user or group (core's settings-backed provider)
- API tokens — create, scope, see last use and revoke personal access tokens, for scripts, n8n and cron jobs
  (PyFinBot's API is used from scripts today with 24h JWTs)
- Sessions & devices — active sign-ins with browser, IP and last seen; "sign out everywhere" (would also lift the
  stateless-JWT "no force-logout" limit services note today)
- Jobs & runs page — schedule, last status, duration, next run, "run now", raw output (core's scheduler);
  PyFinBot's market, dividend and email syncs, BottleBot's scrapes
- Event inspector — a dev/admin page tailing recent `EventBus` events with their payloads
- About page — package and service versions and build info, links to changelogs
- "View as" impersonation — the playground persona switcher as an audited admin feature with a banner (after
  `register_audit`)
- Settings import/export — a user's or the app's settings as JSON
- `CrudViews(model, fields, permissions)` — list/detail/create/edit/delete pages from a SQLAlchemy model, on core's
  query helpers and greentechhub-ui's tables and forms
- Saved views — a table's filter, sort, columns and page size saved per user or shared with a group, pinnable
- Webhooks — outbound subscriptions with a delivery log page, and a signed inbound `/hooks/{name}` endpoint
- `/metrics` for Prometheus, and a `/summary` contract (a few stat values per app) for a GreenTechHub portal
- Backup & restore view — trigger a database dump, list and download backups (on the jobs runner)
- Dev toolbar — debug-mode bar with identity, granted permissions, resolved settings and where each came from,
  request timing and the htmx target

### v1.0 — Validated in production
- [ ] BottleBot's retrofit fully on it
- [ ] PyFinBot's greenfield build fully on it

## 🔄 Migration Tracking

### BottleBot
Its open items are under M3 above.

### PyFinBot
Nothing open: it runs on this package throughout (auth, settings, permissions, roles, logging, health, API error
handlers, query paging, login throttling). Its own follow-ups are in PyFinBot's `todo.md`.

### Market Watch (planned)
- [ ] Not started — builds on this from day one, same as PyFinBot

[← Back to README](README.md)

# ✅ TODO / Milestones

> Open work only: remove an item when it ships — its release note lands in CHANGELOG.md automatically (release-please). See [README.md](README.md) for context and [docs/](docs/) for the detailed design behind each item.

> Shipped work is recorded in [CHANGELOG.md](CHANGELOG.md) and on the [Releases page](https://github.com/GreenMachine582/greentechhub-fastapi/releases) — this file only tracks what's still open.

How work lands: a gap a service hits is fixed in core first when it's framework-free, then here, then in
greentechhub-ui. Releases go in that order and the services bump their pins last. Develop across the repos with
local GTH mode (`scripts/use-local-gth.sh`, see [CONTRIBUTING.md](CONTRIBUTING.md)).

## 🗺️ Milestones

Cross-repo order (with greentechhub-core and greentechhub-ui): consumers live (M3) → ui breaking release (M4) →
PyFinBot ready (M6) → v1.0. M1, M2, M4 (ui v0.19) and M5 shipped; see the CHANGELOG.

### M3 Consumers live — in progress
- PyFinBot runs on this package throughout. Left on its side: the `forward_auth` switch once Authentik is live. This
  package is ready for it (`register_core` + `TRUSTED_PROXIES`); validating Authentik's JWT is core's TODO.
- BottleBot (lowest priority; it has no login yet):
  - [ ] Adopt `register_auth`, if/when BottleBot grows a login
  - [ ] Adopt `register_permissions`/`register_settings` alongside `register_auth` (same trigger)
  - [ ] Replace watchlist's `_watchlist_page_params`/`_next_url` with `query.page_params`/`query.next_page_url`
    (v0.7)

### M6 PyFinBot ready — shipped
This package's share shipped in v0.17.0 (see the CHANGELOG): `register_csp`, `register_admin`, personal API tokens,
`register_error_pages`, `get_owned_or_404` and `require_cookie_csrf`. PyFinBot's `todo.md` holds the adoption PRs.

### Ideas — not scheduled
Each follows the settings/roles pattern: a core model or protocol, a `*Views` class here, a greentechhub-ui template,
one `register_*` call. Who wants it is noted where known.
- Users admin — list, search, disable, force a password reset, assign roles inline (builds on `RoleAdminViews`
  and `RegisterViews`)
- System status page — core health checks as a page (status, last checked, response time), admin-only with an
  optional public summary
- Feature flags page — see and toggle flags per app, user or group (core's settings-backed provider)
- Sessions & devices — active sign-ins with browser, IP and last seen; "sign out everywhere" (would also lift the
  stateless-JWT "no force-logout" limit services note today; PyFinBot accepts that limit for now, and M6.3 covers
  its scripts)
- Jobs & runs page — schedule, last status, duration, next run, "run now", raw output (core's scheduler);
  PyFinBot's market, dividend and email syncs, BottleBot's scrapes
- Event inspector — a dev/admin page tailing recent `EventBus` events with their payloads
- About page — package and service versions and build info, links to changelogs
- "View as" impersonation — the playground persona switcher as an audited admin feature with a banner
  (`register_audit` is in, so it's unblocked)
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
It runs on this package throughout: auth (bearer and personal API tokens included), settings, permissions, roles and
the Admin nav, audit, CSRF (pages and cookie-authenticated API calls), CSP, error pages, logging, health, API error
handlers, query paging, login throttling and the test fixtures. What's left is adopting each release's new pieces, a
PR each in PyFinBot's `todo.md`.

### Market Watch (planned)
- [ ] Not started — builds on this from day one, same as PyFinBot

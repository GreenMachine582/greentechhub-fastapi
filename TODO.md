[← Back to README](README.md)

# ✅ TODO / Milestones

> Open work only: remove an item when it ships — its release note lands in CHANGELOG.md automatically (release-please). See [README.md](README.md) for context and [docs/](docs/) for the detailed design behind each item.

> Shipped work is recorded in [CHANGELOG.md](CHANGELOG.md) and on the [Releases page](https://github.com/GreenMachine582/greentechhub-fastapi/releases) — this file only tracks what's still open.

## 🗺️ Milestones

Cross-repo order (with greentechhub-core and greentechhub-ui): Accounts (M1) → Notifications & email (M2) →
consumers live (M3) → ui breaking release (M4) → display & data (M5) → v1.0.

### Accounts (M1)
- [ ] CSRF tokens on the auth forms — opt-in on `LoginViews`/`RegisterViews`, passing `csrf_token` to the template
  and checking it on POST; needs greentechhub-ui's sign-in and sign-up pages to render the hidden field first (the
  rest of login hardening, throttling and one generic error, is done)

### Notifications & email (M2)
- [ ] Email verification — optional; gates login until the address is confirmed

### Ideas — not scheduled
Each follows the settings/roles pattern: a core model or protocol, a `*Views` class here, a greentechhub-ui template,
one `register_*` call.
- `register_admin(app)` — an "Admin" nav group collecting the admin views below, gated through nav permissions
- Users admin — list, search, disable, force a password reset, assign roles inline (builds on `RoleAdminViews`;
  needed once register lands)
- System status page — core health checks as a page (status, last checked, response time), admin-only with an
  optional public summary
- Feature flags page — see and toggle flags per app, user or group (core's settings-backed provider)
- API tokens — create, scope, see last use and revoke personal access tokens, for scripts, n8n and cron jobs
- Sessions & devices — active sign-ins with browser, IP and last seen; "sign out everywhere"
- Jobs & runs page — schedule, last status, duration, next run, "run now", raw output (core's scheduler)
- Event inspector — a dev/admin page tailing recent `EventBus` events with their payloads
- About page — package and service versions and build info, links to changelogs
- "View as" impersonation — the playground persona switcher as an audited admin feature with a banner
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
- [ ] Adopt `register_auth`, if/when BottleBot grows a login (lowest priority)
- [ ] Adopt `register_permissions`/`register_settings` alongside `register_auth` (same trigger, lowest priority)
- [ ] Replace watchlist's `_watchlist_page_params`/`_next_url` with `query.page_params`/`query.next_page_url` (v0.7)

### PyFinBot
Nothing open: it runs on this package throughout (auth, settings, permissions, roles, logging, health, API error
handlers, query paging). Its own follow-ups are in PyFinBot's `todo.md`.

### Market Watch (planned)
- [ ] Not started — builds on this from day one, same as PyFinBot

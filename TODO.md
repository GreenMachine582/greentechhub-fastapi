[← Back to README](README.md)

# ✅ TODO / Milestones

> Open work only: remove an item when it ships — its release note lands in CHANGELOG.md automatically (release-please). See [README.md](README.md) for context and [docs/](docs/) for the detailed design behind each item.

> Shipped work is recorded in [CHANGELOG.md](CHANGELOG.md) and on the [Releases page](https://github.com/GreenMachine582/greentechhub-fastapi/releases) — this file only tracks what's still open.

How work lands: a gap a service hits is fixed in core first when it's framework-free, then here, then in
greentechhub-ui. Releases go in that order and the services bump their pins last. Develop across the repos with
local GTH mode (`scripts/use-local-gth.sh`, see [CONTRIBUTING.md](CONTRIBUTING.md)).

## 🗺️ Milestones

Cross-repo order (with greentechhub-core and greentechhub-ui): consumers live (M3) → ui breaking release (M4) →
PyFinBot ready (M6) → v1.0. M1, M2 and M5 shipped; see the CHANGELOG.

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

### M6 PyFinBot ready — next
What PyFinBot still needs from this package. One PR each, in this order; PyFinBot's `todo.md` holds the adoption PR
for each once it ships.

- [ ] 1. `feat(security): register_csp`
  - **Why:** greentechhub-ui v0.17's shell is CSP-ready (nonces on every script), but each FastAPI service
    hand-writes the nonce middleware and context processor from ui's `docs/contract.md` › Content-Security-Policy.
    `SecurityHeadersMiddleware` leaves CSP out on purpose. PyFinBot needs a strict policy, plus a `frame-src` for
    its Grafana `gth_embed_card`.
  - **Scope:**
    - a per-request `csp_nonce` on `request.state`, which `ui_context` passes to templates;
    - a `Content-Security-Policy` header, with ui's recommended policy as the default;
    - `frame_src=` / `connect_src=` extras (e.g. the Grafana origin);
    - `setdefault`, so a route can send its own;
    - opt-in, like `register_csrf`.
  - **Done when:** a page's scripts carry the nonce under the header, and ui's playground can take its policy from
    it.
- [ ] 2. `feat(admin): register_admin`
  - **Why:** PyFinBot now has two admin pages (Roles, Audit log), and more will follow (users admin).
  - **Scope:**
    - an "Admin" `NavItem` group whose children are the mounted admin views (`RoleAdminViews`, `AuditViews`), each
      with its permission as `required_permission`;
    - the group shows only when one of its children does.
    - Plain dicts, so it needs no ui change: ui's `nav_visible` already filters by permission.
  - **Done when:** PyFinBot's nav shows Roles and Audit log under Admin, to admins only.
- [ ] 3. `feat(auth): personal API tokens`
  - **Why:** PyFinBot's API is used from scripts with 24h login JWTs, which can't be revoked (a known limitation in
    its `todo.md`).
  - **Scope:**
    - an `ApiTokenViews` section in Settings: create (the token shown once), list with last use, revoke;
    - `register_auth(bearer=True)` also resolves a hashed personal token;
    - a token's scopes are permissions, capped by its owner's.
  - **Needs:** core's API token store (core TODO › API tokens).
  - **Done when:** a script authenticates with a personal token, and revoking it refuses the next call.

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
It runs on this package throughout (auth, settings, permissions, roles, logging, health, API error handlers, query
paging, login throttling). What's left is adopting the newer pieces, each a PR in PyFinBot's `todo.md`: the test
fixtures, `register_audit`, CSRF on htmx forms and bearer API auth, then M6 above as it ships.

### Market Watch (planned)
- [ ] Not started — builds on this from day one, same as PyFinBot

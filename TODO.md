[← Back to README](README.md)

# ✅ TODO / Milestones

> This file is a living checklist — tick items off as they land instead of regenerating it. See [README.md](README.md) for context and [docs/](docs/) for the detailed design behind each item.

## 🗺️ Milestones

Mirrors `greentechhub-core`'s phasing, one step behind so there's always something to adapt.

### v0.1 — Registration shell
Once `greentechhub-core`'s `config`/`logging`/`health`/`proxy` land.

- [x] `registration` — `register_logging`, `register_core`, `register_health` ([docs/registration.md](docs/registration.md))

### v0.2 — Query, exceptions
Once `greentechhub-core`'s `query`/`security`/`types` land.

- [x] `query` — `PageParams` adapter ([docs/query.md](docs/query.md))
- [x] `exception_handlers` ([docs/exceptions.md](docs/exceptions.md))

### v0.3 — Auth, dependencies
Once `greentechhub-core`'s `identity`/`permissions` land.

- [x] `auth` — `local` adapter ([docs/auth.md](docs/auth.md))
- [x] `dependencies` ([docs/modules.md](docs/modules.md#dependencies))

### v0.4 — Flash, events
Once `greentechhub-core`'s `events`/`feature_flags` land.

- [x] `flash` ([docs/modules.md](docs/modules.md#flash-and-events))
- [x] `events` integration ([docs/modules.md](docs/modules.md#flash-and-events)) — decided 2026-09:
      `register_events(app, on_startup=…, on_shutdown=…)` + `Depends(get_event_publisher)` — lifespan
      is the future home of the Redis backend's connect/disconnect.

### v0.5 — Authentik-backed auth
- [x] `auth`'s `forward_auth` path ([docs/auth.md](docs/auth.md)) — shipped 2026-09-12:
      `AuthentikIdentityProvider()` wired via `register_auth`; `ProxyHeadersMiddleware`
      sets `request.state.trusted_proxy` from the request's real remote_addr as the
      one trust signal `forward_auth`'s `get_current_user` reads.

### v0.6 — Login/logout view scaffolding
- [x] `auth.LoginViews` ([docs/auth.md](docs/auth.md)) — extracted from PyFinBot's first
      web UI pass rather than planned upfront: PyFinBot hand-wrote the full local-auth
      login/logout flow (render form, check credentials, issue session JWT, set/clear
      cookie, redirect) and only the credential check was actually service-specific.
      `LoginViews` is an ABC a service subclasses, implementing just
      `authenticate(user_id, password) -> Identity | None` — deliberately
      session/ORM-agnostic, so a subclass fetches its own DB session rather than this
      class taking an opinion on how. Added `jinja2`/`python-multipart` as real
      dependencies (previously only pulled in transitively by consumers).

### v0.7 — Page-route helpers
- [x] `dependencies.require_page_identity(login_url)` ([docs/auth.md](docs/auth.md)) — the
      browser-page counterpart to `get_current_identity`: 303 to the login page, or
      `401` + `HX-Redirect` for HTMX requests (a 303 would be swapped into the fragment).
      Extracted from PyFinBot's Stocks/Transactions pages.
- [x] `query.page_params(default_size)` + `query.next_page_url(path, page, filters)`
      ([docs/query.md](docs/query.md)) — the "load more" glue both BottleBot
      (`_watchlist_page_params`/`_next_url`) and PyFinBot hand-wrote.

### v1.0 — Validated in production
- [ ] BottleBot's retrofit fully on it
- [ ] PyFinBot's greenfield build fully on it

## 🔄 Migration Tracking

Per-service retrofit progress.

### BottleBot
- [x] Swap hand-rolled `/health` for `register_health` — done 2026-09-22; see BottleBot's own
      `TODO.md` for the `/activity` rename this required (BottleBot's old `/health` was a human
      dashboard, not a liveness check, and `register_health`'s paths aren't configurable)
- [x] Swap ad-hoc pagination for the `query` adapter — done 2026-09-22, this adapter's first real
      consumer anywhere; see BottleBot's own `TODO.md` for what it took (only `page`/`size` was
      adoptable — `sort`/`filter` don't apply to data grouped in Python — and BottleBot had to
      write its own `Page` → `next_url` glue for `gth_pagination`, since no such helper exists
      here or in `greentechhub-core`)
- [ ] Adopt `register_auth`, if/when BottleBot grows a login (lowest priority)
- [ ] Replace watchlist's `_watchlist_page_params`/`_next_url` with `query.page_params`/`query.next_page_url` (v0.7)

### PyFinBot
- [ ] Register everything from `greentechhub-fastapi` from the start (greenfield)
- [ ] Follow-up pass on the PyFinBot web interface brief — it currently references `greentechhub-core`'s auth adapter directly rather than this package

### Market Watch (planned)
- [ ] Not started — builds on this from day one, same as PyFinBot

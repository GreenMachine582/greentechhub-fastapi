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

### v1.0 — Validated in production
- [ ] BottleBot's retrofit fully on it
- [ ] PyFinBot's greenfield build fully on it

## 🔄 Migration Tracking

Per-service retrofit progress.

### BottleBot
- [x] Swap hand-rolled `/health` for `register_health` — done 2026-09-22; see BottleBot's own
      `TODO.md` for the `/activity` rename this required (BottleBot's old `/health` was a human
      dashboard, not a liveness check, and `register_health`'s paths aren't configurable)
- [ ] Swap ad-hoc pagination for the `query` adapter
- [ ] Adopt `register_auth`, if/when BottleBot grows a login (lowest priority)

### PyFinBot
- [ ] Register everything from `greentechhub-fastapi` from the start (greenfield)
- [ ] Follow-up pass on the PyFinBot web interface brief — it currently references `greentechhub-core`'s auth adapter directly rather than this package

### Market Watch (planned)
- [ ] Not started — builds on this from day one, same as PyFinBot

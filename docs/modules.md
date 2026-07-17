[← Back to README](../README.md)

# 🧩 Middleware, Flash, Events, Dependencies

The smaller modules that don't warrant their own doc yet — see [docs/registration.md](registration.md), [docs/auth.md](auth.md), [docs/query.md](query.md), [docs/health.md](health.md), and [docs/exceptions.md](exceptions.md) for the higher-detail ones.

## Middleware

Wired via `register_core(app, settings)`, see [docs/registration.md](registration.md).

## Flash and events

Flash producing `greentechhub-core`'s `FlashMessage` type, and startup/shutdown hooks wiring its event publisher into the FastAPI app lifecycle — see the README Scope table for what each does; neither has more detail than that yet.

## Dependencies

Small `Depends`-ready helpers beyond auth (current identity, feature-flag lookups, pagination params) — grows only when a real service needs a new helper, not scoped up front, matching `greentechhub-core`'s own bias against dumping-ground modules.

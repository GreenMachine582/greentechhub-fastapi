# ⚡ greentechhub-fastapi

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg?logo=opensourceinitiative&logoColor=white)](LICENSE)
[![Status: Active Development](https://img.shields.io/badge/Status-Active%20Development-brightgreen.svg)](TODO.md)
[![Python](https://img.shields.io/badge/Python-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![pytest](https://img.shields.io/badge/pytest-0A9EDC.svg?logo=pytest&logoColor=white)](https://docs.pytest.org/)

## 🎯 Objective

The FastAPI/Starlette-specific adapter package: turns `greentechhub-core`'s framework-independent contracts (identity, health checks, query types, config, events) into actual middleware, `Depends`-injectable dependencies, routers, and exception handlers that a FastAPI service can register with a few function calls. Everything here `import fastapi`/`import starlette`; nothing here duplicates logic `greentechhub-core` already owns. It wires a consuming service's *own* database/cache into `greentechhub-core`'s checks — it doesn't provision or own any infrastructure itself.

## 🧩 Scope

| Module | Responsibility | Doc |
|---|---|---|
| `registration` | `register_core(app)`, `register_logging(app)`, `register_health(app)`, `register_auth(app)` — one-call wiring instead of every service hand-assembling middleware | [docs/registration.md](docs/registration.md) |
| `middleware` | Request-ID injection, timing, security headers — thin ASGI middleware wrapping `greentechhub-core`'s pure logic (e.g. `proxy` header parsing) | [docs/modules.md](docs/modules.md#middleware) |
| `auth` | FastAPI `Depends(get_current_user)` built on `greentechhub-core`'s `IdentityProvider`; ships `local` (dev) and `forward_auth` (Authentik) configurations, selected via one setting | [docs/auth.md](docs/auth.md) |
| `health` | A router exposing `/health`/`/health/ready`, running `greentechhub-core`'s health checks against this service's actual dependencies | [docs/health.md](docs/health.md) |
| `query` | Converts FastAPI `Query(...)` parameters into `greentechhub-core`'s `PageRequest`/`Filter`/`Sort`, and renders results as a `Page` envelope | [docs/query.md](docs/query.md) |
| `exception_handlers` | Registers handlers translating `greentechhub-core`'s exception types into the shared JSON error envelope (API routes) or an HTML error page (web routes) | [docs/exceptions.md](docs/exceptions.md) |
| `flash` | Cookie/session-based one-time messages, producing `greentechhub-core`'s `FlashMessage` type | [docs/modules.md](docs/modules.md) |
| `events` | Startup/shutdown hooks wiring `greentechhub-core`'s event publisher into the FastAPI app lifecycle | [docs/modules.md](docs/modules.md) |
| `dependencies` | Small `Depends`-ready helpers beyond auth (current identity, feature-flag lookups, pagination params) | [docs/modules.md](docs/modules.md#dependencies) |

## 📚 Docs

| Doc | Covers |
|---|---|
| [docs/registration.md](docs/registration.md) | 🔌 The one-call `register_*` service-registration pattern (read this first) |
| [docs/auth.md](docs/auth.md) | 🔐 The `local`/`forward_auth` `IdentityProvider` adapters |
| [docs/query.md](docs/query.md) | 🔍 `PageParams` and the `fastapi-pagination` boundary |
| [docs/health.md](docs/health.md) | 🩺 The `/health` router |
| [docs/exceptions.md](docs/exceptions.md) | ⚠️ `ApplicationError` → HTTP response translation |
| [docs/modules.md](docs/modules.md) | 🧩 Middleware, flash, events, dependencies |
| [docs/versioning.md](docs/versioning.md) | 🏷️ Semver policy & distribution |
| [docs/testing.md](docs/testing.md) | 🧪 Reference-app + contract testing strategy |

## 🗺️ Status & Roadmap

v0.1 through v0.4 have shipped — registration, middleware, query/exceptions, local auth, and flash/events are all built and tested. Only v0.5 (`forward_auth`, blocked on a real Authentik instance) and v1.0 (production validation) remain. The phased rollout and per-service migration tracking are a living checklist in [TODO.md](TODO.md).

## 📄 Licence

[MIT](LICENSE) © 2026 Matthew Johnson

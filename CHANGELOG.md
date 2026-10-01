# Changelog

All notable changes to `greentechhub-fastapi`. Versions follow semver (pre-1.0: a breaking change bumps the minor
version). From v0.8.0 on, entries are written by [release-please](https://github.com/googleapis/release-please)
from conventional commits; the same notes are published as
[GitHub Releases](https://github.com/GreenMachine582/greentechhub-fastapi/releases).

## [0.9.0](https://github.com/GreenMachine582/greentechhub-fastapi/compare/v0.8.0...v0.9.0) (2026-10-01)


### Features

* **permissions:** register_permissions and require_permission ([#7](https://github.com/GreenMachine582/greentechhub-fastapi/issues/7)) ([d061930](https://github.com/GreenMachine582/greentechhub-fastapi/commit/d061930be0caaff62aa1c029cac9e9017f6da16e))
* **permissions:** role assignment admin page ([#15](https://github.com/GreenMachine582/greentechhub-fastapi/issues/15)) ([802eb81](https://github.com/GreenMachine582/greentechhub-fastapi/commit/802eb81f15ef0a8b74e67447cbef595c790c804a))
* **settings:** register_settings and SettingsViews ([#14](https://github.com/GreenMachine582/greentechhub-fastapi/issues/14)) ([3318cdb](https://github.com/GreenMachine582/greentechhub-fastapi/commit/3318cdb888d92cbb6b379d1de8d33ec17d9359da))


### Build

* **deps:** pin greentechhub-core v0.7.0 ([#8](https://github.com/GreenMachine582/greentechhub-fastapi/issues/8)) ([0078b85](https://github.com/GreenMachine582/greentechhub-fastapi/commit/0078b853da77100ac5f1de2a235488eeeb9c2f05))

## [0.8.0](https://github.com/GreenMachine582/greentechhub-fastapi/compare/v0.7.0...v0.8.0) (2026-09-24)

### Features

* **htmx:** `hx_response(trigger)` — the bodyless 204 carrying `HX-Trigger` (takes e.g. `greentechhub_ui.toast()`).
* **templating:** `ui_context` context processor (supplies `current_path`) and `mount_static_dirs(app, mapping)`.
  No dependency on `greentechhub-ui` — values and directories are passed in.

## [0.7.0](https://github.com/GreenMachine582/greentechhub-fastapi/compare/v0.6.0...v0.7.0) (2026-09-23)

### Features

* **dependencies:** `require_page_identity(login_url)` — the browser-page login guard (303, or `HX-Redirect` for
  htmx requests).
* **query:** `page_params(default_size)` and `next_page_url(path, page, filters)` — the "load more" paging glue.

## [0.6.0](https://github.com/GreenMachine582/greentechhub-fastapi/compare/v0.5.0...v0.6.0) (2026-09-22)

### Features

* **auth:** `LoginViews` — reusable local-auth login/logout routes.

## [0.5.0](https://github.com/GreenMachine582/greentechhub-fastapi/releases/tag/v0.5.0) (2026-09-13)

### Features

* Registration shell (`register_logging`, `register_core`, `register_health`), `PageParams` query parsing, JSON
  exception envelope.
* **auth:** local adapter + `get_current_identity`; `forward_auth` adapter backed by `AuthentikIdentityProvider`.
* **flash:** signed-cookie flash messages; **events:** lifespan startup/shutdown publishing.

### Bug Fixes

* **middleware:** stamp `trusted_proxy` state from the pre-rewrite remote address.

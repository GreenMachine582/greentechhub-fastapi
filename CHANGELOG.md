# Changelog

All notable changes to `greentechhub-fastapi`. Versions follow semver (pre-1.0: a breaking change bumps the minor
version). From v0.8.0 on, entries are written by [release-please](https://github.com/googleapis/release-please)
from conventional commits; the same notes are published as
[GitHub Releases](https://github.com/GreenMachine582/greentechhub-fastapi/releases).

## [0.15.0](https://github.com/GreenMachine582/greentechhub-fastapi/compare/v0.14.0...v0.15.0) (2026-10-07)


### Features

* **auth:** bearer tokens for API routes ([#61](https://github.com/GreenMachine582/greentechhub-fastapi/issues/61)) ([9b2bcf2](https://github.com/GreenMachine582/greentechhub-fastapi/commit/9b2bcf2ff16d193e50e3519ef03d1e3a4bc82961))
* **forms:** field errors from a ValidationError ([#65](https://github.com/GreenMachine582/greentechhub-fastapi/issues/65)) ([af467b9](https://github.com/GreenMachine582/greentechhub-fastapi/commit/af467b955e5f9890af1b342ab0d20e49e4cd499e))
* **logging:** register_logging service, version and uvicorn ([#63](https://github.com/GreenMachine582/greentechhub-fastapi/issues/63)) ([bcea8e4](https://github.com/GreenMachine582/greentechhub-fastapi/commit/bcea8e4f2dfd9c9ed3ccef5b130d6cb3f69de695))
* **query:** CSV downloads ([#64](https://github.com/GreenMachine582/greentechhub-fastapi/issues/64)) ([fd43bf1](https://github.com/GreenMachine582/greentechhub-fastapi/commit/fd43bf1f8ccdc6e72dea620544781e09662b260b))


### Bug Fixes

* **query:** bad sort or filter input is a 400 ([#62](https://github.com/GreenMachine582/greentechhub-fastapi/issues/62)) ([9ddd358](https://github.com/GreenMachine582/greentechhub-fastapi/commit/9ddd358e2913e4ae160b03d8d61c9f482e40f50e))

## [0.14.0](https://github.com/GreenMachine582/greentechhub-fastapi/compare/v0.13.0...v0.14.0) (2026-10-06)


### Features

* **auth:** throttled API logins ([#56](https://github.com/GreenMachine582/greentechhub-fastapi/issues/56)) ([ec55f24](https://github.com/GreenMachine582/greentechhub-fastapi/commit/ec55f24b210643709122ce738aaa13b8291d2193))
* **settings:** the page context points the bell at the notification centre ([#55](https://github.com/GreenMachine582/greentechhub-fastapi/issues/55)) ([99c37a3](https://github.com/GreenMachine582/greentechhub-fastapi/commit/99c37a3a7add7768381b0067a8ff0c4cd0e8496e))

## [0.13.0](https://github.com/GreenMachine582/greentechhub-fastapi/compare/v0.12.0...v0.13.0) (2026-10-05)


### Features

* **auth:** opt-in CSRF on the auth forms ([#49](https://github.com/GreenMachine582/greentechhub-fastapi/issues/49)) ([cfc597a](https://github.com/GreenMachine582/greentechhub-fastapi/commit/cfc597a6910095816ab75f26f2eca4ca8ffbd224))
* **auth:** sign-up can ask for an email and confirm it ([#50](https://github.com/GreenMachine582/greentechhub-fastapi/issues/50)) ([3754e41](https://github.com/GreenMachine582/greentechhub-fastapi/commit/3754e41d8aa5c5c292ee3ebb403f604692afc6d7))
* **settings:** confirm a changed profile email ([#51](https://github.com/GreenMachine582/greentechhub-fastapi/issues/51)) ([9329323](https://github.com/GreenMachine582/greentechhub-fastapi/commit/93293235c7c3786bc8ca6ae9066765605e148d4e))

## [0.12.0](https://github.com/GreenMachine582/greentechhub-fastapi/compare/v0.11.0...v0.12.0) (2026-10-05)


### Features

* **auth:** email verification ([#46](https://github.com/GreenMachine582/greentechhub-fastapi/issues/46)) ([5ec94d6](https://github.com/GreenMachine582/greentechhub-fastapi/commit/5ec94d68cda914ab49850fe806289dea68f452ac))
* **auth:** login throttling on LoginViews ([#39](https://github.com/GreenMachine582/greentechhub-fastapi/issues/39)) ([e1832c6](https://github.com/GreenMachine582/greentechhub-fastapi/commit/e1832c65b2a9a43c26040b4727e3e3a03d26d1e0))
* **auth:** password reset views ([#45](https://github.com/GreenMachine582/greentechhub-fastapi/issues/45)) ([d7898fe](https://github.com/GreenMachine582/greentechhub-fastapi/commit/d7898fe554c4092c0d91796b9b143cfa86427c67))
* **auth:** RegisterViews for self-service sign-up ([#35](https://github.com/GreenMachine582/greentechhub-fastapi/issues/35)) ([430657d](https://github.com/GreenMachine582/greentechhub-fastapi/commit/430657d93f6fac08c05fd03d3afef743cf3a5a48))
* **auth:** sign-up follows core's self-signup setting ([#38](https://github.com/GreenMachine582/greentechhub-fastapi/issues/38)) ([8652a7e](https://github.com/GreenMachine582/greentechhub-fastapi/commit/8652a7e0b9c7872a04b9c765db66b3a17db09c3e))
* **email:** register_email and notify by email ([#43](https://github.com/GreenMachine582/greentechhub-fastapi/issues/43)) ([ee9ba33](https://github.com/GreenMachine582/greentechhub-fastapi/commit/ee9ba336e9755f6f6d99b497031a4bdb71aa58e7))
* **notifications:** register_notifications and notify ([#41](https://github.com/GreenMachine582/greentechhub-fastapi/issues/41)) ([98a6543](https://github.com/GreenMachine582/greentechhub-fastapi/commit/98a65432d38c8af457dbcaeaa01d87489ee0f947))
* **query:** validate filters against allowed fields ([#44](https://github.com/GreenMachine582/greentechhub-fastapi/issues/44)) ([38d35bf](https://github.com/GreenMachine582/greentechhub-fastapi/commit/38d35bf6644fda23c668362c21b66aa1c8660a8a))
* **settings:** a change-password section ([#36](https://github.com/GreenMachine582/greentechhub-fastapi/issues/36)) ([86cd71a](https://github.com/GreenMachine582/greentechhub-fastapi/commit/86cd71a406ac8b35f141b014ceadeff8da729794))
* **settings:** a profile section ([#40](https://github.com/GreenMachine582/greentechhub-fastapi/issues/40)) ([f18056b](https://github.com/GreenMachine582/greentechhub-fastapi/commit/f18056b1cf2e71fea88929ed69f9596f6277df29))


### Build

* **deps:** greentechhub-core v0.10.0 ([#37](https://github.com/GreenMachine582/greentechhub-fastapi/issues/37)) ([c1db78b](https://github.com/GreenMachine582/greentechhub-fastapi/commit/c1db78b191794280218a8993bcf251b140ce5e94))
* **deps:** greentechhub-core v0.11.0 ([#42](https://github.com/GreenMachine582/greentechhub-fastapi/issues/42)) ([e3ba1c0](https://github.com/GreenMachine582/greentechhub-fastapi/commit/e3ba1c0e1797deaf2b53b199654bc68515447fef))

## [0.11.0](https://github.com/GreenMachine582/greentechhub-fastapi/compare/v0.10.0...v0.11.0) (2026-10-03)


### Features

* **auth:** LoginViews uses greentechhub-ui's login page by default ([#31](https://github.com/GreenMachine582/greentechhub-fastapi/issues/31)) ([2a0658a](https://github.com/GreenMachine582/greentechhub-fastapi/commit/2a0658afb5853fc21b3e4c961fbc0cb2dda69a72))
* **exceptions:** honour core's status hint and BadRequestError ([#27](https://github.com/GreenMachine582/greentechhub-fastapi/issues/27)) ([0fe7707](https://github.com/GreenMachine582/greentechhub-fastapi/commit/0fe7707f9f0c03fe513d772b9edb0f42b8c3e176))
* **exceptions:** register_api_error_handlers for /api envelopes ([#28](https://github.com/GreenMachine582/greentechhub-fastapi/issues/28)) ([3780da6](https://github.com/GreenMachine582/greentechhub-fastapi/commit/3780da669430a2debe66b0c8653559570ea32d43))
* **query:** JSON filter groups ([#30](https://github.com/GreenMachine582/greentechhub-fastapi/issues/30)) ([9cf4dfd](https://github.com/GreenMachine582/greentechhub-fastapi/commit/9cf4dfd7e8b42a33e205410faf9b7cc15f1da7ab))
* **settings:** the opt-in site banner ([#29](https://github.com/GreenMachine582/greentechhub-fastapi/issues/29)) ([0636cb6](https://github.com/GreenMachine582/greentechhub-fastapi/commit/0636cb66a397bdace30f2f6efd1ba0a2533907b9))

## [0.10.0](https://github.com/GreenMachine582/greentechhub-fastapi/compare/v0.9.0...v0.10.0) (2026-10-02)


### Features

* **settings:** secret settings in SettingsViews ([#21](https://github.com/GreenMachine582/greentechhub-fastapi/issues/21)) ([b91ce6b](https://github.com/GreenMachine582/greentechhub-fastapi/commit/b91ce6b77d25b7d17a630330e4410707351bd9f2))
* **settings:** send users to their landing page after login ([#22](https://github.com/GreenMachine582/greentechhub-fastapi/issues/22)) ([d3ae099](https://github.com/GreenMachine582/greentechhub-fastapi/commit/d3ae099a7d95c3f462318180aaaa121ebf512135))


### Build

* **deps:** pin greentechhub-core v0.8.0 ([#20](https://github.com/GreenMachine582/greentechhub-fastapi/issues/20)) ([73c5504](https://github.com/GreenMachine582/greentechhub-fastapi/commit/73c550406dd1601eed6a09ee3b0fcf9bbc6270fe))

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

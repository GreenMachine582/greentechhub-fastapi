"""settings — the per-request and route-level counterparts to
registration.settings.register_settings, over greentechhub-core's Settings.

- SettingsContextMiddleware: installed (innermost) by register_settings.
  For page requests — `Accept: text/html`, or an htmx request — it resolves
  the current user, their granted permissions (when register_permissions
  ran) and their effective settings once, onto request.state. JSON and
  static requests skip it, so they never touch the settings store.
- settings_context: a Jinja2Templates context processor turning that into
  greentechhub-ui's optional template keys: current_user, granted,
  user_settings, theme_mode / theme_save_url, user_menu_items, logout_url.
  Context processors are sync, which is why the middleware does the async
  work up front.
- get_settings_service / get_effective_settings: Depends() helpers.
- get_secret(key): a Depends() factory for a secret setting's plaintext,
  for server code (e.g. an IMAP login), never a template.
- landing_url: the user's chosen landing page (core's landing_page_setting),
  which LoginViews redirects to after a login.
- self_signup_open: core's self_signup_setting, which RegisterViews and
  LoginViews' "Create account" link follow.
- SettingsViews: the /settings page, its two section saves and the theme
  toggle's save endpoint, in LoginViews' style. It renders greentechhub-ui's
  settings_page.html / settings_section.html by default, passing data only:
  nothing here imports greentechhub-ui. Opt-in sections: a Profile (the
  user's display name and email, over the service's own Profile hooks) and
  a Password change.

Secret settings (core's Setting.secret) only ever reach a template or a
JSON response as core's SECRET_SET marker (or None): core's effective()
masks them, and SettingsViews never echoes a submitted one. On save a blank
secret field keeps the stored value and a "<key>.__clear" box resets it,
the contract greentechhub-ui's write-only field posts.

Works with AUTH_ADAPTER=local alone: the user comes from whatever
register_auth installed, and an admin can come from ROLE_BOOTSTRAP
(register_permissions).
"""

import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from greentechhub_core.email import EmailDeliveryError, EmailNotConfiguredError
from greentechhub_core.identity import Identity
from greentechhub_core.permissions import Permission
from greentechhub_core.settings import (
    Setting,
    SettingPermissionError,
    Settings,
    SettingScope,
    SettingType,
)
from greentechhub_core.settings.builtins import (
    LANDING_PAGE_KEY,
    SELF_SIGNUP_KEY,
    SITE_BANNER_KEY,
    SITE_BANNER_TONE_KEY,
)
from starlette.types import ASGIApp, Receive, Scope, Send

from greentechhub_fastapi.auth.dependency import get_current_user
from greentechhub_fastapi.dependencies.identity import require_page_identity
from greentechhub_fastapi.email import email_looks_valid
from greentechhub_fastapi.htmx import _toast_trigger
from greentechhub_fastapi.permissions import _GRANTED_STATE_KEY, RESOLVER_STATE_KEY

if TYPE_CHECKING:
    from greentechhub_fastapi.auth.verify import EmailVerificationViews

logger = logging.getLogger(__name__)

SETTINGS_STATE_KEY = "gth_settings"
THEME_KEY = "ui.theme"

_LOADED = "gth_settings_loaded"
_USER = "gth_settings_user"
_EFFECTIVE = "gth_settings_effective"
_PROFILE = "gth_settings_profile"


@dataclass(frozen=True, slots=True, kw_only=True)
class Profile:
    """A user's profile as SettingsViews' Profile section edits it; an empty
    string means not set. Where it's stored is the service's business."""

    display_name: str = ""
    email: str = ""


class ProfileError(Exception):
    """Raised by a `save_profile` hook for an expected refusal, e.g. an email
    that's taken. `errors` maps fields ("display_name", "email") to their
    messages; the section is shown again with them, status 422."""

    def __init__(self, errors: Mapping[str, list[str]]) -> None:
        super().__init__("; ".join(m for messages in errors.values() for m in messages))
        self.errors = {field: list(messages) for field, messages in errors.items()}


@dataclass(frozen=True, slots=True, kw_only=True)
class SettingsConfig:
    """What register_settings put on app.state."""

    settings: Settings
    manage_permission: Permission | None
    logout_url: str | None
    url: str | None  # SettingsViews' mount path, when register_settings mounted them
    load_profile: Callable[[Identity], Awaitable[Profile]] | None = None  # SettingsViews' hook


def get_settings_config(app: Any) -> SettingsConfig:
    config = getattr(app.state, SETTINGS_STATE_KEY, None)
    if config is None:
        raise RuntimeError("no settings service: call register_settings(app, ...) first")
    return config


def get_settings_service(request: Request) -> Settings:
    """The core Settings register_settings installed."""
    return get_settings_config(request.app).settings


async def _resolve_user(request: Request) -> Identity | None:
    """The current user via whatever register_auth installed (or a test's
    override) — the same callable Depends(get_current_user) would run."""
    resolver = request.app.dependency_overrides.get(get_current_user)
    if resolver is None:
        return None
    result = resolver(request) if inspect.signature(resolver).parameters else resolver()
    return await result if inspect.isawaitable(result) else result


async def _granted(request: Request, user: Identity | None) -> frozenset[str] | None:
    """The user's granted permissions, shared with get_granted_permissions'
    per-request cache; None when no resolver is registered."""
    cached = getattr(request.state, _GRANTED_STATE_KEY, None)
    if cached is not None:
        return cached
    resolver = getattr(request.app.state, RESOLVER_STATE_KEY, None)
    if resolver is None:
        return None
    granted = await resolver.granted(user)
    setattr(request.state, _GRANTED_STATE_KEY, granted)
    return granted


def _is_page_request(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "") or bool(
        request.headers.get("HX-Request")
    )


class SettingsContextMiddleware:
    """Loads the user, granted permissions and effective settings for page
    requests (see the module docstring). Pure ASGI; register_settings adds
    it innermost, so proxy-header and auth state from outer middleware is
    already in place."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            request = Request(scope)
            if _is_page_request(request):
                user = await _resolve_user(request)
                await _granted(request, user)
                effective = await get_settings_service(request).effective(user)
                load_profile = get_settings_config(request.app).load_profile
                if user is not None and load_profile is not None:
                    setattr(request.state, _PROFILE, await load_profile(user))
                setattr(request.state, _USER, user)
                setattr(request.state, _EFFECTIVE, effective)
                setattr(request.state, _LOADED, True)
        await self.app(scope, receive, send)


async def get_effective_settings(
    request: Request,
    user: Identity | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Every registered setting's value for the current user (anonymous:
    app → env → default). Reuses the middleware's result when it ran."""
    if getattr(request.state, _LOADED, False):
        return getattr(request.state, _EFFECTIVE)
    return await get_settings_service(request).effective(user)


def get_secret(key: str):
    """A dependency returning secret setting `key`'s plaintext for the
    current user (their value, else the app value, else None):

        password: str | None = Depends(get_secret("email.app_password"))

    For server code only; never pass it to a template. Core raises
    ValueError when `key` isn't a secret setting and SecretDecryptError when
    the cipher can't decrypt the stored value (the key changed).
    """

    async def dependency(
        request: Request, user: Identity | None = Depends(get_current_user)
    ) -> str | None:
        return await get_settings_service(request).get_secret(key, user)

    return dependency


async def landing_url(request: Request, identity: Identity | None, *, fallback: str = "/") -> str:
    """Where `identity` lands: their `ui.landing_page` (core's
    landing_page_setting), else its app value or default. `fallback` when
    register_settings didn't run or the registry has no landing-page
    setting, so this is opt-in.

    The value is always one of the setting's choices (core validates it and
    skips a stored page that's no longer one), so it's never an open
    redirect. LoginViews uses it after a login; use it on your own routes
    too, e.g. a "/home" that isn't itself a choice. "/" is never redirected
    automatically, since it may itself be a choice.
    """
    config = getattr(request.app.state, SETTINGS_STATE_KEY, None)
    if config is None or LANDING_PAGE_KEY not in config.settings.registry:
        return fallback
    return await config.settings.get(LANDING_PAGE_KEY, identity) or fallback


async def self_signup_open(request: Request, *, fallback: bool = True) -> bool:
    """Whether self-service sign-up is open: the app's value of core's
    self_signup_setting (SELF_SIGNUP_KEY). `fallback` when register_settings
    didn't run or the registry has no such setting, so this is opt-in.

    RegisterViews.is_open checks it by default, and LoginViews hides its
    "Create account" link while it's off.
    """
    config = getattr(request.app.state, SETTINGS_STATE_KEY, None)
    if config is None or SELF_SIGNUP_KEY not in config.settings.registry:
        return fallback
    return bool(await config.settings.get(SELF_SIGNUP_KEY))


def settings_context(request: Request) -> dict[str, Any]:
    """Jinja2Templates context processor for greentechhub-ui's optional
    keys. Empty when the middleware didn't run (JSON, static), so it's safe
    on every template.

    With core's site_banner_settings() in the registry, a non-empty banner
    message becomes greentechhub-ui's `site_banners` on every page, signed
    in or not (id "site", so a dismissal is remembered per message). A
    service that builds its own `site_banners` too should merge them: a
    later context processor's key replaces this one's.

    With SettingsViews' profile hooks, a signed-in user with a display name
    also gets `user_display_name`, for the user menu to show instead of
    their user ID."""
    if not getattr(request.state, _LOADED, False):
        return {}
    config = get_settings_config(request.app)
    user = getattr(request.state, _USER)
    effective = getattr(request.state, _EFFECTIVE)
    context: dict[str, Any] = {"current_user": user, "user_settings": effective}
    if SITE_BANNER_KEY in config.settings.registry:
        if message := str(effective.get(SITE_BANNER_KEY) or "").strip():
            tone = effective.get(SITE_BANNER_TONE_KEY) or "warn"
            context["site_banners"] = [{"message": message, "tone": tone, "id": "site"}]
    granted = getattr(request.state, _GRANTED_STATE_KEY, None)
    if granted is not None:
        context["granted"] = granted
    if user is None:
        return context
    profile = getattr(request.state, _PROFILE, None)
    if profile is not None and profile.display_name:
        context["user_display_name"] = profile.display_name
    has_theme = THEME_KEY in config.settings.registry
    if has_theme:
        context["theme_mode"] = effective.get(THEME_KEY)
    if config.url:
        context["user_menu_items"] = [{"label": "Settings", "url": config.url, "icon": "sliders"}]
        if has_theme:
            context["theme_save_url"] = f"{config.url}/theme"
    if config.logout_url:
        context["logout_url"] = config.logout_url
    return context


class SettingsViews:
    """The settings page. Pass an instance to
    `register_settings(..., views=SettingsViews(templates=templates))`,
    which mounts it at `url`.

    GET {url}: Preferences (the registry's USER settings) for any signed-in
    user, plus App (its APP settings) when register_settings was given a
    manage_permission the user holds. Anonymous visitors go to login_url.

    POST {url}/preferences and {url}/app: coerce each submitted field, then
    422 with the section re-rendered around its errors, or save and return
    the section with a toast (and greentechhub-ui's `gth:theme` event when
    the theme changed). A preference equal to what the user would get
    without one is reset rather than stored, so saving an untouched form
    doesn't pin today's defaults. A secret setting is write-only: a
    non-blank field saves it (encrypted by core), "<key>.__clear" = "true"
    resets it, and a blank field leaves it as it is.

    POST {url}/theme: the theme toggle's save (form field `theme`), 204.

    Change password (opt-in): pass `change_password`, an async
    (user, current, new) -> bool that returns False when `current` isn't
    the user's password and otherwise stores the new one (hashing it is the
    service's job, as with LoginViews). The page then shows a Password
    section after Preferences, and POST {url}/password checks the fields
    (current given; new at least min_password_length, different from
    current, confirmed) before calling it: 422 with the section's errors,
    or 200 with an empty section and a "Password changed" toast. Passwords
    are never rendered back. Sessions already issued stay valid (they're
    stateless JWTs).

    Profile (opt-in): pass `load_profile`, an async (user) -> Profile, and
    `save_profile`, an async (user, Profile) -> None, both over the
    service's own users table. The page then opens with a Profile section
    (display name and email), and POST {url}/profile strips and checks the
    fields (a display name up to max_display_name_length, an email that
    looks like an address or nothing) before calling save_profile: 422 with
    the section's errors (also from a ProfileError it raises), or 200 with
    the saved section and a "Profile saved" toast. register_settings hands
    load_profile to the page-context middleware, which calls it once per
    page request for a signed-in user, so keep it a cheap lookup; the
    display name reaches templates as `user_display_name`. Pass
    `verification` (an EmailVerificationViews) and a changed, non-empty email
    is sent a confirmation link after the save, with the toast saying so; a
    mail problem is logged, not raised. Whether an address counts as
    confirmed is the service's: save_profile should mark it unconfirmed when
    it changes, and mark_verified confirms it.

    Templates default to greentechhub-ui's ready-made settings_page.html and
    settings_section.html; override the names to use your own.
    """

    page_template: str = "settings_page.html"
    section_template: str = "settings_section.html"
    url: str = "/settings"
    login_url: str = "/login"
    title: str = "Settings"
    preferences_title: str = "Preferences"
    preferences_description: str = "Only you see these."
    app_title: str = "App"
    app_description: str = "These apply to everyone."
    password_title: str = "Password"
    password_description: str = "Change the password you sign in with."
    min_password_length: int = 8
    profile_title: str = "Profile"
    profile_description: str = "How you appear to others."
    max_display_name_length: int = 80

    def __init__(
        self,
        *,
        templates: Jinja2Templates,
        change_password: Callable[[Identity, str, str], Awaitable[bool]] | None = None,
        load_profile: Callable[[Identity], Awaitable[Profile]] | None = None,
        save_profile: Callable[[Identity, Profile], Awaitable[None]] | None = None,
        verification: "EmailVerificationViews | None" = None,
    ) -> None:
        if (load_profile is None) != (save_profile is None):
            raise ValueError("pass load_profile and save_profile together")
        self._templates = templates
        self._change_password = change_password
        self.load_profile = load_profile
        self._save_profile = save_profile
        self._verification = verification
        self._page_identity = require_page_identity(self.login_url)

    def router(self) -> APIRouter:
        router = APIRouter()
        page_identity = self._page_identity

        async def page(request: Request, user: Identity = Depends(page_identity)):
            return await self._page(request, user)

        async def save_preferences(request: Request, user: Identity = Depends(page_identity)):
            return await self._save(request, user, "preferences")

        async def save_app(request: Request, user: Identity = Depends(page_identity)):
            return await self._save(request, user, "app")

        async def save_theme(
            request: Request, user: Identity | None = Depends(get_current_user)
        ):
            return await self._save_theme(request, user)

        router.add_api_route(self.url, page, methods=["GET"])
        router.add_api_route(f"{self.url}/preferences", save_preferences, methods=["POST"])
        router.add_api_route(f"{self.url}/app", save_app, methods=["POST"])
        router.add_api_route(f"{self.url}/theme", save_theme, methods=["POST"])
        if self._change_password is not None:

            async def change_password(request: Request, user: Identity = Depends(page_identity)):
                return await self._save_password(request, user)

            router.add_api_route(f"{self.url}/password", change_password, methods=["POST"])
        if self.load_profile is not None:

            async def save_profile(request: Request, user: Identity = Depends(page_identity)):
                return await self._save_profile_section(request, user)

            router.add_api_route(f"{self.url}/profile", save_profile, methods=["POST"])
        return router

    # sections

    def _definitions(self, settings: Settings, section: str) -> tuple[Setting, ...]:
        scope = SettingScope.USER if section == "preferences" else SettingScope.APP
        return settings.registry.for_scope(scope)

    def _section(self, section: str, definitions, values, errors=None) -> dict[str, Any]:
        title, description = (
            (self.preferences_title, self.preferences_description)
            if section == "preferences"
            else (self.app_title, self.app_description)
        )
        return {
            "id": section,
            "title": title,
            "description": description,
            "settings": definitions,
            "values": values,
            "errors": errors,
            "action": f"{self.url}/{section}",
        }

    async def _can_manage(self, request: Request, user: Identity) -> bool:
        permission = get_settings_config(request.app).manage_permission
        if permission is None:
            return False
        granted = await _granted(request, user)
        return granted is not None and permission in granted

    async def _page(self, request: Request, user: Identity):
        settings = get_settings_service(request)
        values = await settings.effective(user)
        sections = []
        if self.load_profile is not None:
            sections.append(self._profile_section(await self.load_profile(user)))
        preferences = self._definitions(settings, "preferences")
        if preferences:
            sections.append(self._section("preferences", preferences, values))
        if self._change_password is not None:
            sections.append(self._password_section())
        if await self._can_manage(request, user):
            app_settings = self._definitions(settings, "app")
            if app_settings:
                sections.append(self._section("app", app_settings, values))
        return self._templates.TemplateResponse(
            request,
            self.page_template,
            {"page_title": self.title, "settings_sections": sections},
        )

    async def _save(self, request: Request, user: Identity, section: str):
        settings = get_settings_service(request)
        if section == "app" and not await self._can_manage(request, user):
            return Response(status_code=403)
        definitions = self._definitions(settings, section)
        form = await request.form()
        submitted: dict[str, Any] = {}
        errors: dict[str, list[str]] = {}
        # Secrets stay out of `submitted`, so a 422 never echoes one: key →
        # plaintext to save, or None to reset.
        secrets: dict[str, str | None] = {}
        for setting in definitions:
            raw = form.get(setting.key)
            if setting.secret:
                if form.get(f"{setting.key}.__clear") == "true":
                    secrets[setting.key] = None
                elif raw:
                    secrets[setting.key] = str(raw)
                continue
            if raw is None:
                if setting.type is SettingType.BOOL:
                    raw = "false"  # an unchecked checkbox without gth_switch's off_value
                else:
                    continue
            try:
                submitted[setting.key] = settings.registry.coerce(setting.key, str(raw))
            except ValueError as exc:
                errors[setting.key] = [str(exc)]
                submitted[setting.key] = raw
        before = await settings.effective(user)
        if errors:
            return self._render_section(
                request, self._section(section, definitions, before | submitted, errors),
                status_code=422,
            )
        try:
            if section == "preferences":
                await self._write_preferences(settings, user, submitted)
                for key, value in secrets.items():
                    if value is None:
                        await settings.reset_user(user, key)
                    else:
                        await settings.set_user(user, key, value)
            else:
                granted = await _granted(request, user) or frozenset()
                for key, value in submitted.items():
                    await settings.set_app(key, value, granted=granted)
                for key, value in secrets.items():
                    if value is None:
                        await settings.reset_app(key, granted=granted)
                    else:
                        await settings.set_app(key, value, granted=granted)
        except SettingPermissionError:
            return Response(status_code=403)
        after = await settings.effective(user)
        events = {}
        if THEME_KEY in submitted and after.get(THEME_KEY) != before.get(THEME_KEY):
            events["gth:theme"] = after[THEME_KEY]
        title = self.preferences_title if section == "preferences" else self.app_title
        return self._render_section(
            request, self._section(section, definitions, after),
            headers={"HX-Trigger": _toast_trigger(f"{title} saved", events)},
        )

    async def _write_preferences(self, settings: Settings, user: Identity, values) -> None:
        fallback = await settings.effective(None)  # what the user gets without their own value
        for key, value in values.items():
            if value == fallback.get(key):
                await settings.reset_user(user, key)
            else:
                await settings.set_user(user, key, value)

    # profile

    def _profile_section(
        self, profile: Profile, errors: dict[str, list[str]] | None = None
    ) -> dict[str, Any]:
        """The Profile section: two plain str fields (duck-typed settings, so
        greentechhub-ui's settings templates render them as text inputs)."""

        def field(key: str, label: str, help_text: str = "") -> dict[str, Any]:
            return {"key": key, "type": "str", "label": label, "default": "",
                    "help_text": help_text}

        return {
            "id": "profile",
            "title": self.profile_title,
            "description": self.profile_description,
            "settings": [
                field("display_name", "Display name", "Shown instead of your user ID."),
                field("email", "Email"),
            ],
            "values": {"display_name": profile.display_name, "email": profile.email},
            "errors": errors,
            "action": f"{self.url}/profile",
            "submit_label": "Save profile",
        }

    def _check_profile(self, profile: Profile) -> dict[str, list[str]]:
        errors: dict[str, list[str]] = {}
        if len(profile.display_name) > self.max_display_name_length:
            errors["display_name"] = [
                f"Use at most {self.max_display_name_length} characters."
            ]
        if profile.email and not email_looks_valid(profile.email):
            errors["email"] = ["Enter an email address, like name@example.com."]
        return errors

    async def _save_profile_section(self, request: Request, user: Identity):
        assert self._save_profile is not None  # the route is only mounted with the hooks
        form = await request.form()
        profile = Profile(
            display_name=str(form.get("display_name") or "").strip(),
            email=str(form.get("email") or "").strip(),
        )
        errors = self._check_profile(profile)
        before = None
        if not errors:
            if self._verification is not None and self.load_profile is not None:
                before = await self.load_profile(user)
            try:
                await self._save_profile(user, profile)
            except ProfileError as exc:
                errors = exc.errors
        if errors:
            return self._render_section(
                request, self._profile_section(profile, errors), status_code=422
            )
        message = "Profile saved"
        changed = before is not None and profile.email and (
            profile.email.casefold() != before.email.strip().casefold()
        )
        if changed and self._verification is not None:
            message = await self._confirm_email(request, user, profile.email)
        return self._render_section(
            request, self._profile_section(profile),
            headers={"HX-Trigger": _toast_trigger(message, {})},
        )

    async def _confirm_email(self, request: Request, user: Identity, email: str) -> str:
        """Send the changed address its confirmation link; the toast to show."""
        assert self._verification is not None
        try:
            await self._verification.send_link(request, user.subject, email)
        except (EmailDeliveryError, EmailNotConfiguredError, RuntimeError, ValueError) as exc:
            logger.warning("confirmation email for %s not sent: %s", user.subject, exc)
            return "Profile saved, but the confirmation email couldn't be sent."
        return f"Profile saved. We've emailed a link to confirm {email}."

    # change password

    def _password_section(self, errors: dict[str, list[str]] | None = None) -> dict[str, Any]:
        """The Password section: three write-only fields that greentechhub-ui's
        settings templates render as empty password inputs (secret str
        settings, duck-typed), never filled back in."""

        def field(key: str, label: str, help_text: str = "") -> dict[str, Any]:
            return {"key": key, "type": "str", "label": label, "default": "", "secret": True,
                    "help_text": help_text}

        return {
            "id": "password",
            "title": self.password_title,
            "description": self.password_description,
            "settings": [
                field("current_password", "Current password"),
                field("new_password", "New password",
                      f"At least {self.min_password_length} characters."),
                field("new_password_confirm", "Confirm new password"),
            ],
            "values": {},
            "errors": errors,
            "action": f"{self.url}/password",
            "submit_label": "Change password",
        }

    async def _save_password(self, request: Request, user: Identity):
        assert self._change_password is not None  # the route is only mounted with one
        form = await request.form()
        current = str(form.get("current_password") or "")
        new = str(form.get("new_password") or "")
        confirm = str(form.get("new_password_confirm") or "")
        errors: dict[str, list[str]] = {}
        if not current:
            errors["current_password"] = ["Enter your current password."]
        if len(new) < self.min_password_length:
            errors["new_password"] = [f"Use at least {self.min_password_length} characters."]
        elif new == current:
            errors["new_password"] = ["Choose a password different from your current one."]
        elif new != confirm:
            errors["new_password_confirm"] = ["The passwords don't match."]
        if not errors and not await self._change_password(user, current, new):
            errors["current_password"] = ["That isn't your current password."]
        if errors:
            return self._render_section(request, self._password_section(errors), status_code=422)
        return self._render_section(
            request, self._password_section(),
            headers={"HX-Trigger": _toast_trigger("Password changed", {})},
        )

    def _render_section(self, request: Request, section: dict[str, Any], **kwargs):
        return self._templates.TemplateResponse(
            request, self.section_template, {"section": section}, **kwargs
        )

    async def _save_theme(self, request: Request, user: Identity | None):
        settings = get_settings_service(request)
        if THEME_KEY not in settings.registry:
            return Response(status_code=404)
        if user is None:
            return Response(status_code=401)
        form = await request.form()
        try:
            value = settings.registry.coerce(THEME_KEY, str(form.get("theme", "")))
        except ValueError:
            return Response(status_code=422)
        await self._write_preferences(settings, user, {THEME_KEY: value})
        return Response(status_code=204)

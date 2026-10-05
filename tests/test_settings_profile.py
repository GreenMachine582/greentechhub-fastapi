"""SettingsViews' opt-in profile section: shown and routed only with both
hooks, field checks before save_profile, 422 with errors or 200 with a
toast, and the display name reaching templates as user_display_name."""

import json
from html import unescape

import pytest
from fastapi import FastAPI, Request
from greentechhub_core.settings import InMemorySettingsStore

from greentechhub_fastapi import register_permissions, register_settings
from greentechhub_fastapi.settings import Profile, ProfileError, SettingsViews
from tests.conftest import build_app
from tests.test_settings import (  # noqa: F401
    ROLES,
    _get,
    _post,
    _registry,
    _run,
    role_settings,
    templates,
)

GOOD = {"display_name": "  Alice Smith ", "email": " alice@example.com "}


class _Profiles:
    def __init__(self):
        self.store = {"alice": Profile(display_name="Alice", email="alice@old.example")}
        self.loads = 0
        self.saves = 0

    async def load(self, user):
        self.loads += 1
        return self.store.get(user.subject, Profile())

    async def save(self, user, profile):
        self.saves += 1
        if profile.email == "taken@example.com":
            raise ProfileError({"email": ["That email is in use."]})
        self.store[user.subject] = profile


def _app(role_settings, templates, profiles=None) -> FastAPI:  # noqa: F811
    app = build_app(role_settings)
    register_permissions(app, role_settings, roles=ROLES)
    hooks = {"load_profile": profiles.load, "save_profile": profiles.save} if profiles else {}
    register_settings(app, role_settings, registry=_registry(), store=InMemorySettingsStore(),
                      views=SettingsViews(templates=templates, **hooks))

    @app.get("/name")
    async def name(request: Request):
        return templates.TemplateResponse(request, "name.html", {})

    return app


@pytest.fixture
def name_templates(templates, tmp_path):  # noqa: F811
    (tmp_path / "name.html").write_text(
        "NAME {{ user_display_name|default('unset') }}", encoding="utf-8"
    )
    return templates


def test_off_without_the_hooks(role_settings, templates):  # noqa: F811
    app = _app(role_settings, templates)
    assert "SECTION profile" not in _run(app, _get("/settings"), subject="alice").text
    assert _run(app, _post("/settings/profile", GOOD), subject="alice").status_code == 404


def test_both_hooks_are_needed(templates):  # noqa: F811
    with pytest.raises(ValueError, match="together"):
        SettingsViews(templates=templates, load_profile=_Profiles().load)


def test_the_page_opens_with_the_profile_section(role_settings, templates):  # noqa: F811
    page = _run(_app(role_settings, templates, _Profiles()), _get("/settings"),
                subject="alice").text
    assert "SECTION profile keys=display_name,email action=/settings/profile" in page
    assert page.index("SECTION profile") < page.index("SECTION preferences")


def test_saving_stores_the_stripped_profile_and_toasts(role_settings, templates):  # noqa: F811
    profiles = _Profiles()
    response = _run(_app(role_settings, templates, profiles), _post("/settings/profile", GOOD),
                    subject="alice")
    assert response.status_code == 200
    assert json.loads(response.headers["HX-Trigger"])["showToast"]["message"] == "Profile saved"
    assert profiles.store["alice"] == Profile(display_name="Alice Smith", email="alice@example.com")
    assert "VAL display_name=Alice Smith" in response.text and "ERR" not in response.text


def test_empty_fields_clear_the_profile(role_settings, templates):  # noqa: F811
    profiles = _Profiles()
    response = _run(_app(role_settings, templates, profiles),
                    _post("/settings/profile", {"display_name": " ", "email": ""}),
                    subject="alice")
    assert response.status_code == 200
    assert profiles.store["alice"] == Profile()


@pytest.mark.parametrize(("data", "error"), [
    ({**GOOD, "display_name": "x" * 81}, "display_name=Use at most 80 characters."),
    ({**GOOD, "email": "alice"}, "email=Enter an email address, like name@example.com."),
    ({**GOOD, "email": "a@b@c"}, "email=Enter an email address, like name@example.com."),
    ({**GOOD, "email": "al ice@example.com"},
     "email=Enter an email address, like name@example.com."),
    ({**GOOD, "email": "@example.com"}, "email=Enter an email address, like name@example.com."),
])
def test_field_checks_run_before_the_hook(role_settings, templates, data, error):  # noqa: F811
    profiles = _Profiles()
    response = _run(_app(role_settings, templates, profiles), _post("/settings/profile", data),
                    subject="alice")
    assert response.status_code == 422
    assert f"ERR {error}" in unescape(response.text)
    assert profiles.saves == 0


def test_a_refusal_from_the_service_is_a_field_error(role_settings, templates):  # noqa: F811
    profiles = _Profiles()
    response = _run(_app(role_settings, templates, profiles),
                    _post("/settings/profile", {**GOOD, "email": "taken@example.com"}),
                    subject="alice")
    assert response.status_code == 422
    assert "ERR email=That email is in use." in unescape(response.text)
    assert "VAL email=taken@example.com" in response.text  # the submitted values are kept
    assert profiles.store["alice"].display_name == "Alice"


def test_anonymous_cannot_save_a_profile(role_settings, templates):  # noqa: F811
    profiles = _Profiles()
    response = _run(_app(role_settings, templates, profiles), _post("/settings/profile", GOOD))
    assert response.status_code in (303, 401)
    assert profiles.saves == 0


def test_pages_get_the_display_name(role_settings, name_templates):  # noqa: F811
    profiles = _Profiles()
    app = _app(role_settings, name_templates, profiles)
    assert _run(app, _get("/name"), subject="alice").text == "NAME Alice"
    assert profiles.loads == 1
    assert _run(app, _get("/name")).text == "NAME unset"  # anonymous: never loaded
    assert profiles.loads == 1
    assert _run(app, _get("/name"), subject="bob").text == "NAME unset"  # no name set


def test_no_display_name_without_the_hooks(role_settings, name_templates):  # noqa: F811
    app = _app(role_settings, name_templates)
    assert _run(app, _get("/name"), subject="alice").text == "NAME unset"

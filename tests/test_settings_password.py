"""SettingsViews' opt-in change-password section: shown and routed only with
`change_password=`, field checks before the callable, 422 with errors or
200 with a toast, and passwords never rendered back."""

import json
from html import unescape

from fastapi import FastAPI
from greentechhub_core.settings import InMemorySettingsStore

from greentechhub_fastapi import register_permissions, register_settings
from greentechhub_fastapi.settings import SettingsViews
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

GOOD = {"current_password": "old-secret", "new_password": "new-secret-1",
        "new_password_confirm": "new-secret-1"}


class _Passwords:
    def __init__(self):
        self.store = {"alice": "old-secret"}
        self.calls = 0

    async def __call__(self, user, current, new):
        self.calls += 1
        if self.store.get(user.subject) != current:
            return False
        self.store[user.subject] = new
        return True


def _app(role_settings, templates, change_password=None) -> FastAPI:  # noqa: F811
    app = build_app(role_settings)
    register_permissions(app, role_settings, roles=ROLES)
    register_settings(app, role_settings, registry=_registry(), store=InMemorySettingsStore(),
                      views=SettingsViews(templates=templates, change_password=change_password))
    return app


def test_off_without_a_callable(role_settings, templates):  # noqa: F811
    app = _app(role_settings, templates)
    assert "SECTION password" not in _run(app, _get("/settings"), subject="alice").text
    assert _run(app, _post("/settings/password", GOOD), subject="alice").status_code == 404


def test_the_page_shows_the_section_after_preferences(role_settings, templates):  # noqa: F811
    app = _app(role_settings, templates, _Passwords())
    page = _run(app, _get("/settings"), subject="alice").text
    assert ("SECTION password keys=current_password,new_password,new_password_confirm "
            "action=/settings/password") in page
    assert page.index("SECTION preferences") < page.index("SECTION password")


def test_a_valid_change_stores_the_new_password_and_toasts(role_settings, templates):  # noqa: F811
    passwords = _Passwords()
    response = _run(_app(role_settings, templates, passwords), _post("/settings/password", GOOD),
                    subject="alice")
    assert response.status_code == 200
    assert json.loads(response.headers["HX-Trigger"])["showToast"]["message"] == "Password changed"
    assert passwords.store["alice"] == "new-secret-1"
    assert response.text.startswith("SECTION password") and "ERR" not in response.text
    assert "secret" not in response.text  # neither password comes back


def test_field_checks_run_before_the_callable(role_settings, templates):  # noqa: F811
    cases = [
        ({**GOOD, "current_password": ""}, "current_password=Enter your current password."),
        ({**GOOD, "new_password": "short", "new_password_confirm": "short"},
         "new_password=Use at least 8 characters."),
        ({**GOOD, "new_password": "old-secret", "new_password_confirm": "old-secret"},
         "new_password=Choose a password different from your current one."),
        ({**GOOD, "new_password_confirm": "new-secret-2"},
         "new_password_confirm=The passwords don't match."),
    ]
    passwords = _Passwords()
    app = _app(role_settings, templates, passwords)
    for data, error in cases:
        response = _run(app, _post("/settings/password", data), subject="alice")
        assert response.status_code == 422
        assert f"ERR {error}" in unescape(response.text)
        assert "secret" not in response.text
    assert passwords.calls == 0


def test_a_wrong_current_password_is_a_field_error(role_settings, templates):  # noqa: F811
    passwords = _Passwords()
    response = _run(_app(role_settings, templates, passwords),
                    _post("/settings/password", {**GOOD, "current_password": "guess-1234"}),
                    subject="alice")
    assert response.status_code == 422
    assert "ERR current_password=That isn't your current password." in unescape(response.text)
    assert passwords.store["alice"] == "old-secret"


def test_anonymous_cannot_change_a_password(role_settings, templates):  # noqa: F811
    passwords = _Passwords()
    response = _run(_app(role_settings, templates, passwords), _post("/settings/password", GOOD))
    assert response.status_code in (303, 401)
    assert passwords.calls == 0

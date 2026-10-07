"""The auth views' shared pieces: greentechhub-core's settings readers,
role map, password and email checks (core v0.13), and this package's own
FormErrors, EMAIL_SEND_ERRORS, CsrfProtected._render_form and
EmailedLinkViews."""

import greentechhub_core.config as core_config
import greentechhub_core.permissions as core_permissions
from greentechhub_core.email import EMAIL_INVALID, EmailDeliveryError, EmailNotConfiguredError
from greentechhub_core.email import email_looks_valid as core_email_looks_valid
from greentechhub_core.security import PASSWORD_TOO_SHORT, PASSWORDS_DIFFER

from greentechhub_fastapi.auth.emailed_link import ENTER_IDENTIFIER, EmailedLinkViews
from greentechhub_fastapi.auth.errors import FormErrors
from greentechhub_fastapi.auth.register import RegisterViews, RegistrationError
from greentechhub_fastapi.auth.reset import PasswordResetViews
from greentechhub_fastapi.auth.verify import EmailVerificationViews
from greentechhub_fastapi.email import EMAIL_SEND_ERRORS, email_looks_valid
from greentechhub_fastapi.registration import _settings
from greentechhub_fastapi.registration.permissions import read_role_map
from greentechhub_fastapi.settings import ProfileError


def test_the_settings_readers_and_role_map_are_cores():
    assert _settings.setting_value is core_config.setting_value
    assert _settings.read_list_setting is core_config.read_list_setting
    assert _settings.read_str_setting is core_config.read_str_setting
    assert read_role_map is core_permissions.read_role_map


def test_the_email_check_is_cores():
    assert email_looks_valid is core_email_looks_valid
    assert EMAIL_INVALID == "Enter an email address, like name@example.com."


def test_form_errors_is_the_base_of_both_hook_errors():
    for cls in (RegistrationError, ProfileError):
        error = cls({"email": ["Taken."], "user_id": ["Too short.", "Odd."]})
        assert isinstance(error, FormErrors)
        assert error.errors == {"email": ["Taken."], "user_id": ["Too short.", "Odd."]}
        assert str(error) == "Taken.; Too short.; Odd."


def test_email_send_errors_cover_every_best_effort_send():
    assert set(EMAIL_SEND_ERRORS) == {EmailDeliveryError, EmailNotConfiguredError, RuntimeError,
                                      ValueError}


def test_reset_and_verify_share_the_emailed_link_base():
    for cls in (PasswordResetViews, EmailVerificationViews):
        assert issubclass(cls, EmailedLinkViews)
    assert ENTER_IDENTIFIER == "Enter your user ID or email."
    assert PasswordResetViews.token_lifetime != EmailVerificationViews.token_lifetime


def test_the_password_messages_come_from_core():
    class _Views(RegisterViews):
        async def create_user(self, user_id, password):  # pragma: no cover - not called
            raise AssertionError

    views = _Views.__new__(_Views)
    assert views._validate("u", "short", "short") == {
        "password": [PASSWORD_TOO_SHORT.format(min_length=8)]}
    assert views._validate("u", "long-enough", "long-enouhg") == {
        "password_confirm": [PASSWORDS_DIFFER]}

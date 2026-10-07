"""errors — FormErrors, the "show the form again with these messages" error a
service's hook raises: RegisterViews.create_user's RegistrationError and
SettingsViews' save_profile ProfileError are both one of these."""

from collections.abc import Mapping


class FormErrors(Exception):
    """An expected refusal with messages per form field. `errors` maps
    fields to their messages; the view shows the form again with them,
    status 422."""

    def __init__(self, errors: Mapping[str, list[str]]) -> None:
        super().__init__("; ".join(m for messages in errors.values() for m in messages))
        self.errors = {field: list(messages) for field, messages in errors.items()}

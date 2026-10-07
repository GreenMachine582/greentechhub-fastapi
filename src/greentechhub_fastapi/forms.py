"""forms — glue between pydantic validation and greentechhub-ui's forms.

    try:
        data = TransactionCreate(**form)
    except ValidationError as exc:
        return templates.TemplateResponse(request, "_form.html",
                                          {"errors": field_errors(exc), ...}, status_code=422)
"""

from pydantic import ValidationError


def field_errors(exc: ValidationError) -> dict[str, list[str]]:
    """`exc`'s messages by field, the shape greentechhub-ui's form macros take
    (`errors.get("name")`). A nested error is filed under its top-level
    field; a model-level one (no field) under "__all__"."""
    errors: dict[str, list[str]] = {}
    for error in exc.errors():
        field = str(error["loc"][0]) if error["loc"] else "__all__"
        errors.setdefault(field, []).append(error["msg"])
    return errors

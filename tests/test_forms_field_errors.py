"""forms.field_errors: a pydantic ValidationError as greentechhub-ui's
errors-by-field dict."""

from datetime import date

import pytest
from pydantic import BaseModel, ValidationError, field_validator, model_validator

from greentechhub_fastapi.forms import field_errors


class _Address(BaseModel):
    postcode: int


class _Form(BaseModel):
    name: str
    units: float
    when: date
    address: _Address | None = None

    @field_validator("units")
    @classmethod
    def _positive(cls, value):
        if value <= 0:
            raise ValueError("Must be greater than 0.")
        return value

    @model_validator(mode="after")
    def _not_both(self):
        if self.name == "nobody" and self.units == 1:
            raise ValueError("That combination isn't allowed.")
        return self


def _errors(**data):
    with pytest.raises(ValidationError) as caught:
        _Form(**data)
    return field_errors(caught.value)


def test_each_field_gets_its_messages():
    errors = _errors(units="0", when="not-a-date")
    assert set(errors) == {"name", "units", "when"}
    assert errors["units"] == ["Value error, Must be greater than 0."]
    assert errors["name"] == ["Field required"]


def test_a_nested_error_is_filed_under_its_top_level_field():
    errors = _errors(name="x", units=1, when="2025-07-01", address={"postcode": "abc"})
    assert list(errors) == ["address"]


def test_a_model_level_error_goes_under_all():
    errors = _errors(name="nobody", units=1, when="2025-07-01")
    assert errors == {"__all__": ["Value error, That combination isn't allowed."]}

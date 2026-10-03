from greentechhub_core.types import (
    ApplicationError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)

from greentechhub_fastapi.exceptions.render import render_error_body, status_code_for


def test_status_code_for_application_error_is_500():
    assert status_code_for(ApplicationError("boom")) == 500


def test_status_code_for_not_found_error_is_404():
    assert status_code_for(NotFoundError("missing")) == 404


def test_status_code_for_validation_error_is_422():
    assert status_code_for(ValidationError("bad input")) == 422


def test_status_code_for_conflict_error_is_409():
    assert status_code_for(ConflictError("duplicate")) == 409


def test_status_code_for_unauthorized_error_is_401():
    assert status_code_for(UnauthorizedError("no credentials")) == 401


def test_status_code_for_forbidden_error_is_403():
    assert status_code_for(ForbiddenError("not allowed")) == 403


def test_status_code_for_unmapped_subclass_falls_through_mro_to_nearest_ancestor():
    class SpecialNotFoundError(NotFoundError):
        pass

    assert status_code_for(SpecialNotFoundError("still missing")) == 404


def test_render_error_body_shape():
    exc = ValidationError("bad input", details={"field": ["required"]})
    body = render_error_body(exc)
    assert body == {
        "code": "validation_error",
        "message": "bad input",
        "details": {"field": ["required"]},
    }


def test_render_error_body_details_defaults_to_none():
    exc = NotFoundError("missing")
    body = render_error_body(exc)
    assert body["details"] is None


def test_status_code_for_bad_request_error_is_400():
    assert status_code_for(BadRequestError("unparseable id")) == 400


def test_an_errors_own_status_hint_wins_over_its_type():
    assert status_code_for(ApplicationError("mailbox down", status_code=503)) == 503
    assert status_code_for(NotFoundError("gone", status_code=410)) == 410


def test_a_subclass_class_level_hint_is_honoured():
    class UpstreamError(ApplicationError):
        code = "upstream_failed"
        status_code = 502

    assert status_code_for(UpstreamError("down")) == 502
    assert status_code_for(UpstreamError("busy", status_code=503)) == 503


def test_an_out_of_range_hint_falls_back_to_the_type_mapping():
    for bad in (99, 600, 0, -1):
        assert status_code_for(NotFoundError("missing", status_code=bad)) == 404, bad
    assert status_code_for(ConflictError("dup", status_code=True)) == 409  # a bool isn't a status


def test_no_hint_keeps_the_type_mapping():
    assert NotFoundError("missing").status_code is None
    assert status_code_for(NotFoundError("missing")) == 404

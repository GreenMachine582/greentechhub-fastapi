import asyncio

import httpx
from fastapi import FastAPI
from greentechhub_core.types import (
    ApplicationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)

from greentechhub_fastapi.exceptions import register_exception_handlers


def _build_app():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/application-error")
    async def raise_application_error():
        raise ApplicationError("something went wrong")

    @app.get("/not-found")
    async def raise_not_found():
        raise NotFoundError("missing", details={"id": 42})

    @app.get("/validation-error")
    async def raise_validation():
        raise ValidationError("bad input")

    @app.get("/conflict")
    async def raise_conflict():
        raise ConflictError("duplicate")

    @app.get("/unauthorized")
    async def raise_unauthorized():
        raise UnauthorizedError("no credentials")

    @app.get("/forbidden")
    async def raise_forbidden():
        raise ForbiddenError("not allowed")

    return app


async def _get(app, path):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def test_bare_application_error_returns_500():
    app = _build_app()
    response = asyncio.run(_get(app, "/application-error"))
    assert response.status_code == 500
    assert response.json() == {
        "code": "application_error",
        "message": "something went wrong",
        "details": None,
    }


def test_not_found_error_returns_404_with_details():
    app = _build_app()
    response = asyncio.run(_get(app, "/not-found"))
    assert response.status_code == 404
    assert response.json() == {"code": "not_found", "message": "missing", "details": {"id": 42}}


def test_validation_error_returns_422():
    app = _build_app()
    response = asyncio.run(_get(app, "/validation-error"))
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_conflict_error_returns_409():
    app = _build_app()
    response = asyncio.run(_get(app, "/conflict"))
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


def test_unauthorized_error_returns_401():
    app = _build_app()
    response = asyncio.run(_get(app, "/unauthorized"))
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_forbidden_error_returns_403():
    app = _build_app()
    response = asyncio.run(_get(app, "/forbidden"))
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"

import asyncio

import httpx
from fastapi import FastAPI, HTTPException
from greentechhub_core.types import ApplicationError, UnauthorizedError

from greentechhub_fastapi import register_api_error_handlers, register_exception_handlers


def _build_app(prefix="/api", **kwargs):
    app = FastAPI()
    register_exception_handlers(app)
    register_api_error_handlers(app, prefix, **kwargs)

    @app.get("/api/items")
    async def items(limit: int):
        return {"limit": limit}

    @app.get("/api/teapot")
    async def teapot():
        raise HTTPException(status_code=418, detail="I'm a teapot")

    @app.get("/api/token")
    async def token():
        # what OAuth2PasswordBearer raises without a token
        raise HTTPException(status_code=401, detail="Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})

    @app.get("/api/me")
    async def me():
        raise UnauthorizedError("Could not validate credentials")

    @app.get("/api/sync")
    async def sync():
        raise ApplicationError("Mailbox unreachable", code="email_sync_failed", status_code=503)

    @app.get("/page")
    async def page(limit: int):
        return {"limit": limit}

    @app.get("/page/me")
    async def page_me():
        raise UnauthorizedError("Sign in")

    @app.get("/apix/items")
    async def apix(limit: int):
        return {"limit": limit}

    return app


def _request(app, method, path):
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path)

    return asyncio.run(run())


def _get(app, path):
    return _request(app, "GET", path)


def test_unknown_api_route_is_a_404_envelope_but_pages_keep_fastapis_default():
    app = _build_app()
    api = _get(app, "/api/nope")
    assert api.status_code == 404
    assert api.json() == {"code": "not_found", "message": "Not Found", "details": None}
    page = _get(app, "/nope")
    assert page.status_code == 404 and page.json() == {"detail": "Not Found"}


def test_wrong_method_is_a_405_envelope():
    response = _request(_build_app(), "POST", "/api/teapot")
    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"


def test_http_exception_keeps_its_status_and_headers():
    teapot = _get(_build_app(), "/api/teapot")
    assert teapot.status_code == 418
    assert teapot.json() == {"code": "http_418", "message": "I'm a teapot", "details": None}
    token = _get(_build_app(), "/api/token")
    assert token.status_code == 401
    assert token.json()["code"] == "unauthorized"
    assert token.headers["www-authenticate"] == "Bearer"


def test_validation_errors_are_an_envelope_under_the_prefix_only():
    api = _get(_build_app(), "/api/items?limit=lots")
    assert api.status_code == 422
    body = api.json()
    assert (body["code"], body["message"]) == ("validation_error", "Invalid request")
    assert body["details"][0]["loc"] == ["query", "limit"]
    page = _get(_build_app(), "/page?limit=lots")
    assert page.status_code == 422 and set(page.json()) == {"detail"}


def test_unauthorized_error_gets_the_bearer_challenge_under_the_prefix():
    api = _get(_build_app(), "/api/me")
    assert api.status_code == 401
    assert api.json() == {"code": "unauthorized", "message": "Could not validate credentials",
                          "details": None}
    assert api.headers["www-authenticate"] == "Bearer"
    page = _get(_build_app(), "/page/me")
    assert page.status_code == 401 and "www-authenticate" not in page.headers
    no_challenge = _get(_build_app(www_authenticate=None), "/api/me")
    assert no_challenge.status_code == 401 and "www-authenticate" not in no_challenge.headers


def test_prefix_matches_whole_segments_and_is_normalised():
    app = _build_app(prefix="api/")  # normalised to /api
    assert _get(app, "/api/items?limit=lots").json()["code"] == "validation_error"
    apix = _get(app, "/apix/items?limit=lots")
    assert apix.status_code == 422 and set(apix.json()) == {"detail"}  # not the API


def test_other_application_errors_still_use_register_exception_handlers():
    response = _get(_build_app(), "/api/sync")
    assert response.status_code == 503
    assert response.json() == {"code": "email_sync_failed", "message": "Mailbox unreachable",
                               "details": None}

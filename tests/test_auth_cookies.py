import asyncio

import httpx
from fastapi import FastAPI, Response

from greentechhub_fastapi.auth.cookies import clear_session_cookie, create_session_cookie


def _build_app():
    app = FastAPI()

    @app.get("/login")
    async def login(response: Response):
        create_session_cookie(response, "the-token")
        return {"ok": True}

    @app.get("/logout")
    async def logout(response: Response):
        clear_session_cookie(response)
        return {"ok": True}

    return app


async def _get(app, path):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def test_create_session_cookie_sets_expected_flags():
    app = _build_app()
    response = asyncio.run(_get(app, "/login"))
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 1
    cookie = cookies[0]
    assert cookie.startswith("gth_session=the-token")
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie


def test_clear_session_cookie_expires_it():
    app = _build_app()
    response = asyncio.run(_get(app, "/logout"))
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 1
    cookie = cookies[0]
    assert cookie.startswith("gth_session=")
    assert "Max-Age=0" in cookie

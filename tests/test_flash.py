import asyncio

import httpx
import pytest
from fastapi import Depends, FastAPI, Response
from greentechhub_core.types import FlashMessage

from greentechhub_fastapi import flash
from greentechhub_fastapi.flash import flash_context, get_flashes
from greentechhub_fastapi.registration.flash import register_flash


@pytest.fixture(autouse=True)
def _restore_flash_serializer():
    original = flash._serializer
    yield
    flash._serializer = original


def _build_app(settings):
    app = FastAPI()
    register_flash(app, settings)

    @app.get("/set-one")
    async def set_one(response: Response):
        flash.flash(response, "Saved!", kind="success")
        return {"ok": True}

    @app.get("/set-two")
    async def set_two(response: Response):
        flash.flash(response, "First", kind="info")
        flash.flash(response, "Second", kind="warning")
        return {"ok": True}

    @app.get("/read")
    async def read(flashes: list[FlashMessage] = Depends(get_flashes)):
        return flash_context(flashes)

    return app


async def _get(app, path, cookies=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.get(path)


def test_flash_then_get_flashes_round_trips_through_a_redirect(settings):
    app = _build_app(settings)
    set_response = asyncio.run(_get(app, "/set-one"))
    cookie = set_response.cookies.get("gth_flash")
    assert cookie

    read_response = asyncio.run(_get(app, "/read", cookies={"gth_flash": cookie}))
    assert read_response.json() == {"flashes": [{"message": "Saved!", "kind": "success"}]}


def test_get_flashes_clears_the_cookie(settings):
    app = _build_app(settings)
    set_response = asyncio.run(_get(app, "/set-one"))
    cookie = set_response.cookies.get("gth_flash")

    read_response = asyncio.run(_get(app, "/read", cookies={"gth_flash": cookie}))
    set_cookie_headers = read_response.headers.get_list("set-cookie")
    assert any(h.startswith("gth_flash=") and "Max-Age=0" in h for h in set_cookie_headers)


def test_multiple_flash_calls_in_one_handler_all_survive(settings):
    app = _build_app(settings)
    set_response = asyncio.run(_get(app, "/set-two"))
    cookie = set_response.cookies.get("gth_flash")

    read_response = asyncio.run(_get(app, "/read", cookies={"gth_flash": cookie}))
    assert read_response.json() == {
        "flashes": [
            {"message": "First", "kind": "info"},
            {"message": "Second", "kind": "warning"},
        ]
    }


def test_missing_cookie_returns_no_flashes(settings):
    app = _build_app(settings)
    response = asyncio.run(_get(app, "/read"))
    assert response.json() == {"flashes": []}


def test_tampered_cookie_returns_no_flashes_without_raising(settings):
    app = _build_app(settings)
    response = asyncio.run(_get(app, "/read", cookies={"gth_flash": "not-a-real-signed-value"}))
    assert response.json() == {"flashes": []}


def test_flash_before_register_flash_raises_runtime_error():
    flash._serializer = None

    with pytest.raises(RuntimeError):
        flash.flash(Response(), "Saved!")


def test_flash_context_shapes_an_already_resolved_list():
    result = flash_context([FlashMessage(message="Hi", kind="info")])
    assert result == {"flashes": [{"message": "Hi", "kind": "info"}]}

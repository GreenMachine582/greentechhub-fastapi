"""register_csp: a per-request nonce on request.state.csp_nonce and in
ui_context, and greentechhub-ui's recommended Content-Security-Policy with it,
unless a route sends its own."""

import asyncio
import re

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.templating import Jinja2Templates
from jinja2 import DictLoader, Environment

from greentechhub_fastapi import register_csp
from greentechhub_fastapi.middleware import DEFAULT_CSP, CspMiddleware, content_security_policy
from greentechhub_fastapi.templating import ui_context

UI_RECOMMENDED = (
    "default-src 'self'; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-src 'self'; "
    "frame-ancestors 'self'; base-uri 'self'; form-action 'self'; object-src 'none'"
)


def _app(**kwargs) -> FastAPI:
    app = FastAPI()
    env = Environment(loader=DictLoader({"page.html": '<script nonce="{{ csp_nonce }}"></script>'}),
                      autoescape=True)
    templates = Jinja2Templates(env=env, context_processors=[ui_context])

    @app.get("/nonce")
    async def nonce(request: Request):
        return {"nonce": getattr(request.state, "csp_nonce", None)}

    @app.get("/page")
    async def page(request: Request):
        return templates.TemplateResponse(request, "page.html")

    @app.get("/context")
    async def context(request: Request):
        return {"keys": sorted(ui_context(request))}

    @app.get("/own")
    async def own():
        return PlainTextResponse("x", headers={"Content-Security-Policy": "default-src 'none'"})

    if kwargs.pop("register", True):
        register_csp(app, **kwargs)
    return app


async def _get(app, *paths):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return [await client.get(path) for path in paths]


def _nonce_in(header: str) -> str:
    return re.search(r"'nonce-([^']+)'", header).group(1)


def test_the_default_is_uis_recommended_policy():
    assert DEFAULT_CSP == UI_RECOMMENDED
    assert content_security_policy() == UI_RECOMMENDED


def test_the_header_carries_the_requests_nonce_and_it_differs_per_request():
    first, second = asyncio.run(_get(_app(), "/nonce", "/nonce"))
    nonce = first.json()["nonce"]
    assert len(nonce) >= 20
    assert first.headers["Content-Security-Policy"] == UI_RECOMMENDED.format(nonce=nonce)
    assert second.json()["nonce"] != nonce


def test_templates_get_the_nonce_through_ui_context():
    [response] = asyncio.run(_get(_app(), "/page"))
    nonce = _nonce_in(response.headers["Content-Security-Policy"])
    assert response.text == f'<script nonce="{nonce}"></script>'


def test_frame_src_and_connect_src_extras():
    app = _app(frame_src=["https://grafana.example"], connect_src=["https://api.example", "wss://ws.example"])
    [response] = asyncio.run(_get(app, "/nonce"))
    header = response.headers["Content-Security-Policy"]
    assert "frame-src 'self' https://grafana.example;" in header
    assert "connect-src 'self' https://api.example wss://ws.example;" in header
    assert "frame-ancestors 'self';" in header


def test_a_custom_policy_gets_the_nonce():
    app = _app(policy="script-src 'self' 'nonce-{nonce}' 'unsafe-eval'")
    [response] = asyncio.run(_get(app, "/nonce"))
    assert response.headers["Content-Security-Policy"] == (
        f"script-src 'self' 'nonce-{response.json()['nonce']}' 'unsafe-eval'"
    )


def test_a_routes_own_policy_is_kept():
    [response] = asyncio.run(_get(_app(), "/own"))
    assert response.headers.get_list("Content-Security-Policy") == ["default-src 'none'"]


def test_without_register_csp_there_is_no_header_or_nonce():
    nonce, context = asyncio.run(_get(_app(register=False), "/nonce", "/context"))
    assert "Content-Security-Policy" not in nonce.headers
    assert nonce.json() == {"nonce": None}
    assert "csp_nonce" not in context.json()["keys"]


def test_ui_context_has_csp_nonce_when_registered():
    [context] = asyncio.run(_get(_app(), "/context"))
    assert "csp_nonce" in context.json()["keys"]


def test_register_csp_must_run_before_the_app_starts():
    app = _app()
    asyncio.run(_get(app, "/nonce"))
    with pytest.raises(RuntimeError, match="before the app starts"):
        register_csp(app)


def test_non_http_scopes_pass_through():
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope)

    asyncio.run(CspMiddleware(inner)({"type": "lifespan"}, None, None))
    assert seen == [{"type": "lifespan"}]

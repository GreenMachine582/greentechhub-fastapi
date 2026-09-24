import asyncio
import json
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from jinja2 import DictLoader

from greentechhub_fastapi.htmx import hx_response
from greentechhub_fastapi.templating import mount_static_dirs, ui_context


async def _get(app, path):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def test_hx_response_is_a_bodyless_204_with_the_trigger():
    resp = hx_response('{"showToast": {"message": "Saved", "kind": "success"}}')
    assert resp.status_code == 204 and resp.body == b""
    assert json.loads(resp.headers["HX-Trigger"])["showToast"]["message"] == "Saved"


def test_hx_response_json_encodes_a_mapping_and_can_carry_content():
    resp = hx_response({"closeModal": True, "rowsChanged": {"id": 7}},
                       status_code=200, content="<tr></tr>", headers={"X-Extra": "1"})
    assert json.loads(resp.headers["HX-Trigger"]) == {"closeModal": True, "rowsChanged": {"id": 7}}
    assert resp.status_code == 200 and resp.body == b"<tr></tr>"
    assert resp.headers["X-Extra"] == "1" and resp.headers["content-type"].startswith("text/html")


def test_ui_context_supplies_current_path():
    templates = Jinja2Templates(directory=".", context_processors=[ui_context])
    templates.env.loader = DictLoader({"p.html": "[{{ current_path }}]"})
    app = FastAPI()

    @app.get("/stocks/{item}")
    async def page(request: Request, item: str):
        return templates.TemplateResponse(request, "p.html")

    assert asyncio.run(_get(app, "/stocks/7")).text == "[/stocks/7]"


def test_mount_static_dirs_serves_each_prefix(tmp_path: Path):
    (tmp_path / "a").mkdir()
    (tmp_path / "t").mkdir()
    (tmp_path / "a" / "x.js").write_text("js")
    (tmp_path / "t" / "theme.css").write_text("css")
    app = FastAPI()
    mount_static_dirs(app, {"/gth-assets": tmp_path / "a", "/gth-static": str(tmp_path / "t")})
    assert asyncio.run(_get(app, "/gth-assets/x.js")).text == "js"
    assert asyncio.run(_get(app, "/gth-static/theme.css")).text == "css"
    assert {r.name for r in app.routes if hasattr(r, "name")} >= {"gth-assets", "gth-static"}


def test_this_package_does_not_import_greentechhub_ui():
    """No dependency on greentechhub-ui: header values and directories are
    passed in. Checked on the import statements, not docstring examples."""
    import ast

    import greentechhub_fastapi

    for path in Path(greentechhub_fastapi.__file__).parent.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(n.split(".")[0] == "greentechhub_ui" for n in names), path

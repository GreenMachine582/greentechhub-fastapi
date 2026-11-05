"""FolderPickerViews: the folder browser partial over core's list_folders —
a path's subfolders with breadcrumbs, hidden folders on request, errors as
messages, roots it can't leave, and the picker's target id passed back."""

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi.templating import Jinja2Templates
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity
from markupsafe import escape

from greentechhub_fastapi.folders import FOLDER_ERRORS, FolderPickerViews
from tests.conftest import build_app

# A stand-in for greentechhub-ui's folder_browser.html: it prints the data.
BROWSER = """AT {{ listing.path }} UP {{ listing.parent or "-" }} ROOTS {{ listing.at_roots }}
CRUMBS {% for c in listing.breadcrumbs %}{{ c.label }}>{% endfor %}
{% for f in listing.entries %}F {{ f.name }} {{ f.hidden }}
{% endfor %}HIDDEN {{ listing.hidden_count }} SHOW {{ show_hidden }} TARGET {{ target or "-" }}
ERROR {{ listing.error or "-" }} {{ listing.error_message or "" }}
URL {{ browse_url }} LABEL {{ roots_label }}"""


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "music"
    for name in ("Albums/2024", "Singles", ".trash"):
        (root / name).mkdir(parents=True)
    (root / "readme.txt").write_text("x")
    return root.resolve()


def _app(settings, tmp_path, **kwargs):
    (tmp_path / "folder_browser.html").write_text(BROWSER, encoding="utf-8")
    app = build_app(settings)
    views = FolderPickerViews(templates=Jinja2Templates(directory=tmp_path), **kwargs)
    app.include_router(views.router())
    return app


def _get(app, params, subject="alice"):
    async def go():
        cookies = None
        if subject:
            provider = DevelopmentIdentityProvider(secret_key="test-secret")
            cookies = {"gth_session": provider.issue(
                Identity(subject=subject, username=subject, email=None, groups=[], claims={}))}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test", cookies=cookies) as client:
            return await client.get("/folders", params=params,
                                    headers={"Accept": "text/html"})

    return asyncio.run(go())


def test_lists_a_folder(settings, tmp_path, tree):
    response = _get(_app(settings, tmp_path), {"path": str(tree), "target": "library-path"})
    assert response.status_code == 200
    text = response.text
    assert f"AT {tree} UP {tree.parent} ROOTS False" in text
    assert "F Albums False\nF Singles False\nHIDDEN 1 SHOW False" in text
    assert "TARGET library-path" in text and "ERROR - " in text
    assert text.splitlines()[1].endswith("music>")
    assert "URL /folders LABEL This computer" in text


def test_hidden_folders_on_request(settings, tmp_path, tree):
    text = _get(_app(settings, tmp_path), {"path": str(tree), "hidden": "1"}).text
    assert "F .trash True" in text and "SHOW True" in text


def test_errors_come_with_a_message(settings, tmp_path, tree):
    app = _app(settings, tmp_path)
    text = _get(app, {"path": str(tree / "nope")}).text
    assert f"ERROR not_found {escape(FOLDER_ERRORS['not_found'])}" in text
    assert "ERROR invalid" in _get(app, {"path": "relative"}).text


def test_roots_limit_browsing(settings, tmp_path, tree):
    app = _app(settings, tmp_path, roots=[str(tree)])
    at_root = _get(app, {}).text
    assert f"AT {tree} UP - " in at_root and "F Albums" in at_root
    outside = _get(app, {"path": str(tree.parent)}).text
    assert "ERROR outside_roots" in outside and "F " not in outside


def test_a_target_that_isnt_a_plain_id_is_dropped(settings, tmp_path, tree):
    text = _get(_app(settings, tmp_path), {"path": str(tree), "target": "x');alert(1"}).text
    assert "TARGET -" in text


def test_anonymous_goes_to_login(settings, tmp_path):
    response = _get(_app(settings, tmp_path), {}, subject=None)
    assert response.status_code == 303 and response.headers["location"] == "/login"

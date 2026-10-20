"""notify takes what greentechhub-ui's toast() returns as it is: its
HX-Trigger JSON text, not only the decoded value or the bare detail."""

import asyncio
import json

import pytest

from greentechhub_fastapi.notifications import notify
from tests.test_notifications import _app
from tests.test_settings import role_settings  # noqa: F401


def test_a_toast_string_is_stored_like_its_detail(role_settings):  # noqa: F811
    app, store = _app(role_settings)
    # What toast("Sync finished", "success", title="Email sync") returns: JSON text.
    trigger = json.dumps({"showToast": {"message": "Sync finished", "kind": "success",
                                        "title": "Email sync"}})
    stored = asyncio.run(notify(app, "alice", trigger, category="sync"))
    assert stored is not None
    assert (stored.message, stored.kind, stored.title, stored.category) == (
        "Sync finished", "success", "Email sync", "sync")
    assert [n.message for n in store.list_for_sync("alice")] == ["Sync finished"]


def test_text_that_isnt_json_is_an_error(role_settings):  # noqa: F811
    app, _ = _app(role_settings)
    with pytest.raises(ValueError):
        asyncio.run(notify(app, "alice", "Sync finished"))

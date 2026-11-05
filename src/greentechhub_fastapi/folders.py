"""folders — FolderPickerViews: the browse endpoint behind greentechhub-ui's
gth_folder_picker, over greentechhub-core's list_folders.

GET {url}?path=...&hidden=1&target=<input id> answers the folder browser
partial (folder_browser.html by default) for the picker's modal: the
breadcrumbs, the subfolders, a hidden-folders toggle and the error, if any.
Like the other *Views it passes data only and doesn't import greentechhub-ui.

The listing runs in a worker thread (it touches the disk). With `roots` the
browser can't leave those folders; without them everything the process can
read is browsable, which suits a local single-user app (AUTH_ADAPTER=
single_user), not a shared server.
"""

import asyncio
import re
from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from greentechhub_core.files import FolderListing, list_folders
from greentechhub_core.identity import Identity

from greentechhub_fastapi.dependencies.identity import require_page_identity
from greentechhub_fastapi.permissions import require_page_permission

FOLDER_ERRORS = {
    "permission_denied": "You don't have permission to open this folder.",
    "not_found": "This folder doesn't exist.",
    "not_a_folder": "That's a file, not a folder.",
    "unavailable": "This drive or folder isn't available right now.",
    "outside_roots": "That folder is outside the ones you can browse.",
    "invalid": "Enter a full path, such as C:\\Music or /home/me/music.",
}
"""The message shown for each core FolderError."""

_TARGET = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}")


def listing_dict(listing: FolderListing) -> dict[str, Any]:
    """A FolderListing as template data, with the error's message."""
    return {
        "path": listing.path,
        "parent": listing.parent,
        "at_roots": listing.at_roots,
        "breadcrumbs": [{"label": c.label, "path": c.path} for c in listing.breadcrumbs],
        "entries": [{"name": f.name, "path": f.path, "hidden": f.hidden}
                    for f in listing.entries],
        "hidden_count": listing.hidden_count,
        "truncated": listing.truncated,
        "error": listing.error,
        "error_message": FOLDER_ERRORS.get(listing.error or "", None),
    }


class FolderPickerViews:
    """The folder browser's route. Mount it with
    `app.include_router(FolderPickerViews(templates=templates).router())`
    and point gth_folder_picker's browse_url at `url`.

    GET {url}?path=&hidden=1&target=: `path` empty for the roots (drive
    letters on Windows); `hidden=1` includes hidden folders; `target` is the
    picker input's id, passed back so "Choose this folder" fills the right
    field (ignored unless it's a plain id).

    `roots` (optional) limits browsing to those folders; `permission`
    (optional) gates it, else any signed-in identity may browse.

    The template gets {"listing", "browse_url", "target", "show_hidden",
    "roots_label"}, `listing` a listing_dict() (path, parent, at_roots,
    breadcrumbs, entries, hidden_count, truncated, error, error_message).
    """

    template: str = "folder_browser.html"
    url: str = "/folders"
    login_url: str = "/login"
    roots_label: str = "This computer"
    max_entries: int = 1000

    def __init__(self, *, templates: Jinja2Templates, roots: Sequence[str] | None = None,
                 permission: str | None = None) -> None:
        self._templates = templates
        self.roots = list(roots) if roots is not None else None
        self.permission = permission
        if permission is None:
            self._guard = require_page_identity(self.login_url)
        else:
            self._guard = require_page_permission(permission, self.login_url)

    def router(self) -> APIRouter:
        router = APIRouter()

        async def browse(request: Request, user: Identity = Depends(self._guard)):
            query = request.query_params
            show_hidden = query.get("hidden") in ("1", "true", "on")
            target = query.get("target") or ""
            listing = await asyncio.to_thread(
                list_folders, (query.get("path") or "").strip() or None, roots=self.roots,
                show_hidden=show_hidden, max_entries=self.max_entries)
            return self._templates.TemplateResponse(request, self.template, {
                "listing": listing_dict(listing),
                "browse_url": self.url,
                "target": target if _TARGET.fullmatch(target) else None,
                "show_hidden": show_hidden,
                "roots_label": self.roots_label,
            })

        router.add_api_route(self.url, browse, methods=["GET"])
        return router

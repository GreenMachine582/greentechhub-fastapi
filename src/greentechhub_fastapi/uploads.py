"""uploads — reading an uploaded file with a size cap: the server half of
greentechhub-ui's gth_file_drop (whose client-side check is a convenience,
not a guard).

    @router.post("/import")
    async def import_file(file: UploadFile = File(...)):
        content = await read_upload(file, limit=5 * 1024 * 1024)

read_upload reads at most `limit + 1` bytes, so an oversized upload is never
buffered whole, and raises UploadTooLargeError: core's ApplicationError with
a 413 status hint and the "payload_too_large" code, which
register_exception_handlers / register_api_error_handlers turn into the
{code, message, details} envelope. A page route can catch it and render its
own form error.
"""

from typing import Protocol

from greentechhub_core.types import ApplicationError


class UploadTooLargeError(ApplicationError):
    """An upload over read_upload's limit (HTTP 413)."""

    code = "payload_too_large"
    status_code = 413


class Readable(Protocol):
    """What read_upload reads from: Starlette's UploadFile, or anything with
    an async read(size)."""

    async def read(self, size: int = -1) -> bytes: ...


def _size(limit: int) -> str:
    for unit, scale in (("MB", 1024 * 1024), ("KB", 1024)):
        if limit >= scale:
            return f"{limit / scale:g} {unit}"
    return f"{limit} bytes"


async def read_upload(file: Readable, *, limit: int) -> bytes:
    """The upload's bytes, reading at most `limit + 1`. Raises
    UploadTooLargeError ("File is larger than 5 MB.") when it's larger than
    `limit` bytes."""
    if limit < 0:
        raise ValueError("limit must be zero or more bytes")
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise UploadTooLargeError(f"File is larger than {_size(limit)}.")
    return content

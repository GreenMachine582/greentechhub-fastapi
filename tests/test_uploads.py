"""uploads.read_upload: an upload read with a size cap. At most limit + 1
bytes are read, and over the limit it's UploadTooLargeError, which the API
error handlers answer as a 413 payload_too_large envelope."""

import asyncio
import io

import httpx
import pytest
from fastapi import FastAPI, File, UploadFile

from greentechhub_fastapi.exceptions import register_exception_handlers
from greentechhub_fastapi.uploads import UploadTooLargeError, read_upload

MB = 1024 * 1024


class _File:
    def __init__(self, data: bytes):
        self._data = io.BytesIO(data)
        self.sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.sizes.append(size)
        return self._data.read(size)


def test_within_the_limit_returns_the_bytes():
    assert asyncio.run(read_upload(_File(b"x" * 10), limit=10)) == b"x" * 10


def test_over_the_limit_raises_without_reading_it_all():
    big = _File(b"x" * (3 * MB))
    with pytest.raises(UploadTooLargeError, match=r"^File is larger than 2 MB\.$") as exc:
        asyncio.run(read_upload(big, limit=2 * MB))
    assert big.sizes == [2 * MB + 1]
    assert (exc.value.status_code, exc.value.code) == (413, "payload_too_large")


@pytest.mark.parametrize("limit,label", [(5 * MB, "5 MB"), (1536 * 1024, "1.5 MB"), (2048, "2 KB"),
                                         (100, "100 bytes")])
def test_the_message_names_the_limit(limit, label):
    with pytest.raises(UploadTooLargeError, match=f"larger than {label}"):
        asyncio.run(read_upload(_File(b"x" * (limit + 1)), limit=limit))


def test_a_negative_limit_is_a_programming_error():
    with pytest.raises(ValueError):
        asyncio.run(read_upload(_File(b""), limit=-1))


def test_an_api_route_answers_413_with_the_envelope():
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/upload")
    async def upload(file: UploadFile = File(...)):
        return {"size": len(await read_upload(file, limit=1024))}

    async def post(data: bytes):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/upload", files={"file": ("f.csv", data, "text/csv")})

    assert asyncio.run(post(b"a,b\n")).json() == {"size": 4}
    big = asyncio.run(post(b"x" * 2048))
    assert big.status_code == 413
    body = big.json()
    assert (body["code"], body["message"]) == ("payload_too_large", "File is larger than 1 KB.")

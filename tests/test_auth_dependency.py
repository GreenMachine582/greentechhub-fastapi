import asyncio

import httpx
import pytest
from fastapi import Depends, FastAPI

from greentechhub_fastapi.auth import get_current_user


def test_placeholder_raises_not_implemented_when_called_directly():
    async def _call():
        await get_current_user(request=None)

    with pytest.raises(NotImplementedError):
        asyncio.run(_call())


def test_unregistered_dependency_surfaces_as_server_error():
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(user=Depends(get_current_user)):
        return {"user": user}

    async def _get():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/whoami")

    response = asyncio.run(_get())
    assert response.status_code == 500

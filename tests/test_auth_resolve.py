import asyncio

from fastapi import FastAPI

from greentechhub_fastapi.auth.resolve import resolve_dependency


class _Resource:
    def __init__(self, tag=None):
        self.tag = tag
        self.closed = False


async def _real_dependency():
    resource = _Resource(tag="real")
    try:
        yield resource
    finally:
        resource.closed = True


async def _override_dependency():
    resource = _Resource(tag="override")
    try:
        yield resource
    finally:
        resource.closed = True


async def _use(app, dependency):
    async with resolve_dependency(app, dependency) as resource:
        return resource


def test_resolves_real_dependency_when_no_override():
    app = FastAPI()
    resource = asyncio.run(_use(app, _real_dependency))
    assert resource.tag == "real"


def test_resolves_override_when_set():
    app = FastAPI()
    app.dependency_overrides[_real_dependency] = _override_dependency
    resource = asyncio.run(_use(app, _real_dependency))
    assert resource.tag == "override"


def test_generator_is_closed_after_use():
    app = FastAPI()
    captured = {}

    async def _capture():
        async with resolve_dependency(app, _real_dependency) as resource:
            captured["resource"] = resource
            assert resource.closed is False

    asyncio.run(_capture())
    assert captured["resource"].closed is True

import asyncio
import json

from greentechhub_fastapi.middleware.proxy_headers import ProxyHeadersMiddleware


async def _echo_app(scope, receive, send):
    body = json.dumps(
        {
            "client": scope["client"],
            "scheme": scope["scheme"],
            "headers": {k.decode(): v.decode() for k, v in scope["headers"]},
        }
    ).encode()
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": body})


def _make_scope(*, client, scheme="http", headers=None):
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()
    ]
    return {
        "type": "http",
        "client": client,
        "scheme": scheme,
        "headers": raw_headers,
    }


async def _run(app, scope):
    messages = []

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    body = b"".join(m["body"] for m in messages if m["type"] == "http.response.body")
    return json.loads(body)


def test_untrusted_remote_addr_ignores_forwarded_headers():
    app = ProxyHeadersMiddleware(_echo_app, trusted_proxies=["10.0.0.1"])
    scope = _make_scope(
        client=("203.0.113.5", 12345),
        headers={"X-Forwarded-For": "198.51.100.9", "X-Forwarded-Proto": "https"},
    )
    result = asyncio.run(_run(app, scope))
    assert result["client"] == ["203.0.113.5", 12345]
    assert result["scheme"] == "http"


def test_trusted_remote_addr_applies_forwarded_for_and_proto():
    app = ProxyHeadersMiddleware(_echo_app, trusted_proxies=["10.0.0.1"])
    scope = _make_scope(
        client=("10.0.0.1", 12345),
        headers={"X-Forwarded-For": "198.51.100.9", "X-Forwarded-Proto": "https"},
    )
    result = asyncio.run(_run(app, scope))
    assert result["client"] == ["198.51.100.9", 12345]
    assert result["scheme"] == "https"


def test_no_trusted_proxies_configured_is_a_no_op():
    app = ProxyHeadersMiddleware(_echo_app, trusted_proxies=())
    scope = _make_scope(
        client=("10.0.0.1", 12345),
        headers={"X-Forwarded-For": "198.51.100.9", "X-Forwarded-Proto": "https"},
    )
    result = asyncio.run(_run(app, scope))
    assert result["client"] == ["10.0.0.1", 12345]
    assert result["scheme"] == "http"

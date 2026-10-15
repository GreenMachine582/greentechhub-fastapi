"""register_csp — a Content-Security-Policy with a per-request nonce, for
greentechhub-ui's CSP-ready app shell.

Opt-in like every register_* call. It installs CspMiddleware: each request
gets a nonce on request.state.csp_nonce, which ui_context passes to templates
as `csp_nonce`, and each response gets the policy with that nonce, unless a
route sent its own.
"""

from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI

from greentechhub_fastapi.middleware.csp import CspMiddleware, content_security_policy


def register_csp(
    app: FastAPI,
    settings: Any = None,
    *,
    frame_src: Iterable[str] = (),
    connect_src: Iterable[str] = (),
    policy: str | None = None,
) -> None:
    """Install CspMiddleware with greentechhub-ui's recommended policy.

    Args:
        settings: accepted for symmetry with the other register_* calls.
        frame_src: origins added to frame-src, e.g. a Grafana origin for
            gth_embed_card.
        connect_src: origins added to connect-src.
        policy: a whole policy instead, with `{nonce}` where the nonce goes
            (e.g. one that adds 'unsafe-eval'); frame_src/connect_src are
            then ignored.
    """
    if app.middleware_stack is not None:
        raise RuntimeError("register_csp must run before the app starts")
    if policy is None:
        policy = content_security_policy(frame_src=frame_src, connect_src=connect_src)
    app.add_middleware(CspMiddleware, policy=policy)

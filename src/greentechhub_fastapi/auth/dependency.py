"""get_current_user — the stable Depends() placeholder every route imports.

register_auth(app, settings) installs the real implementation via
app.dependency_overrides[get_current_user] = <adapter impl>. FastAPI's
override dict is keyed by the exact callable object passed to Depends(...),
so this module must stay the single source of the symbol — a route file
importing `from greentechhub_fastapi.auth import get_current_user` and
registration/auth.py importing the same name both bind to the identical
function object, which is what lets `Depends(get_current_user)` behave
differently depending on which adapter was configured, without the route
itself knowing or caring which one. This is the mechanism behind
docs/auth.md's promise that swapping local dev auth for Authentik forward-auth
is a config change, not a code change.

Raises NotImplementedError rather than returning None when no override has
been installed: a misconfigured app (register_auth never called) should fail
loudly on the first request that depends on it, not silently treat every
caller as anonymous.
"""

from fastapi import Request
from greentechhub_core.identity import Identity


async def get_current_user(request: Request) -> Identity | None:
    raise NotImplementedError(
        "register_auth(app, settings) must be called before routes can use "
        "Depends(get_current_user)."
    )

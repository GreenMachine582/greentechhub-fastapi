"""tokens — API tokens for the local adapter: issue_token signs one with
the same DevelopmentIdentityProvider register_auth built (so the session
cookie and an API token are the same kind of JWT), and bearer_scheme
documents `Authorization: Bearer` in OpenAPI, so Swagger's Authorize button
works.

    register_auth(app, settings, bearer=True)

    @router.post("/auth/login")
    async def login(request: Request, form: OAuth2PasswordRequestForm = Depends()):
        identity = await throttled_login(throttle, form.username, check, address=...)
        ...
        return {"access_token": issue_token(request.app, identity), "token_type": "bearer"}

    api = APIRouter(dependencies=[Depends(bearer_scheme("/api/auth/login"))])

    @api.get("/things")
    async def things(identity: Identity = Depends(get_current_identity)): ...
"""

from datetime import timedelta
from typing import Any

from fastapi.security import OAuth2PasswordBearer
from greentechhub_core.identity import DevelopmentIdentityProvider, Identity

#: Where register_auth keeps the local adapter's provider on app.state.
IDENTITY_PROVIDER_STATE_KEY = "gth_identity_provider"


def issue_token(
    app: Any, identity: Identity, *, expires_in: timedelta = timedelta(hours=12)
) -> str:
    """A signed token for `identity`, valid for `expires_in`, that the local
    adapter resolves from `Authorization: Bearer` (register_auth(...,
    bearer=True)) or the session cookie. `app` may be the app or a request.
    Raises RuntimeError unless register_auth set up the local adapter."""
    app = getattr(app, "app", app)
    provider = getattr(app.state, IDENTITY_PROVIDER_STATE_KEY, None)
    if not isinstance(provider, DevelopmentIdentityProvider):
        raise RuntimeError(
            "issue_token needs register_auth(app, settings) with AUTH_ADAPTER=local first"
        )
    return provider.issue(identity, expires_in=expires_in)


def bearer_scheme(token_url: str) -> OAuth2PasswordBearer:
    """An OAuth2 password-flow bearer scheme for a router's dependencies=,
    so OpenAPI lists the token endpoint and Swagger can authorize. It only
    documents the scheme (auto_error=False): get_current_identity and
    require_permission do the checking."""
    return OAuth2PasswordBearer(tokenUrl=token_url, auto_error=False)

"""personal_tokens — resolving a personal API token from `Authorization:
Bearer` (register_auth(..., bearer=True) with register_api_tokens).

A personal token is greentechhub-core's ApiTokenStore plaintext:
generate_token()'s url-safe base64, which never contains the dots a JWT
has, so the local adapter tells the two apart by shape. A resolved token
signs its owner in, with the token's scopes recorded on request.state;
get_granted_permissions then caps the owner's permissions to them.

The Identity it gives has only the owner's subject: roles come from grants
and ROLE_BOOTSTRAP, not from directory groups (ROLE_GROUPS).
"""

from fastapi import Request
from greentechhub_core.identity import Identity
from greentechhub_core.security import ApiTokenStore

#: Where register_api_tokens keeps the store on app.state.
API_TOKENS_STATE_KEY = "gth_api_tokens"
#: request.state: the scopes of the personal token the request signed in with.
API_TOKEN_SCOPES_STATE = "gth_api_token_scopes"
#: The Identity claim naming the personal token's id.
API_TOKEN_CLAIM = "gth_api_token"


def get_api_token_store(request: Request) -> ApiTokenStore | None:
    """The ApiTokenStore register_api_tokens installed, or None."""
    return getattr(request.app.state, API_TOKENS_STATE_KEY, None)


def looks_like_personal_token(token: str) -> bool:
    """A bearer value shaped like a personal token rather than a JWT."""
    return "." not in token


async def resolve_api_token(request: Request, plaintext: str) -> Identity | None:
    """The owner of a valid personal token (recording its use), with its
    scopes on request.state; None when the token is unknown, revoked or
    expired, or no store is registered."""
    store = get_api_token_store(request)
    if store is None:
        return None
    token = await store.verify(plaintext)
    if token is None:
        return None
    setattr(request.state, API_TOKEN_SCOPES_STATE, token.scopes)
    return Identity(subject=token.owner, username=token.owner, email=None, groups=[],
                    claims={API_TOKEN_CLAIM: token.id})


def signed_in_with_api_token(request: Request) -> bool:
    """Whether this request's caller is a personal API token."""
    return getattr(request.state, API_TOKEN_SCOPES_STATE, None) is not None

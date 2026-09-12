"""register_flash — configures flash.py's module-level cookie serializer from
`settings.secret_key`. Must run once before flash()/get_flashes() are used,
same "build the shared thing once at registration time" shape register_auth's
provider already follows.
"""

from fastapi import FastAPI
from greentechhub_core.config import GTHBaseSettings

from greentechhub_fastapi import flash


def register_flash(app: FastAPI, settings: GTHBaseSettings) -> None:
    """Configure flash.py's cookie serializer from `settings.secret_key`.

    `app` is accepted (and unused) for signature consistency with the other
    register_* functions — like register_logging, this configures
    process-global state, not anything attached to `app` itself.
    """
    flash._configure(settings.secret_key)

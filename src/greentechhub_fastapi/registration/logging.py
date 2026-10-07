"""register_logging — wires greentechhub_core's JSON logging into a service's startup.

Named `logging.py` inside a package that also imports the stdlib `logging`
indirectly (via greentechhub_core.logging) — safe for the same reason
greentechhub_core/logging/setup.py's own comment explains: Python 3's import
system is absolute-by-default (PEP 328), so a bare `import logging` elsewhere
always resolves to the stdlib module regardless of this file's location.
"""

import logging

from fastapi import FastAPI
from greentechhub_core.config import GTHBaseSettings
from greentechhub_core.logging import configure_logging

#: uvicorn's own loggers, which it sets up with plain-text handlers before
#: importing the app.
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def register_logging(
    app: FastAPI,
    settings: GTHBaseSettings,
    *,
    service: str | None = None,
    version: str | None = None,
    uvicorn: bool = False,
) -> None:
    """Configure the root logger for this service: one JSON object per line
    at settings.log_level, tagged with `service` and `version` when given.

    `uvicorn=True` also sends uvicorn's own loggers through that JSON
    handler (their plain-text handlers are removed and they propagate to the
    root), so every line the process writes is JSON.

    `app` is accepted (and unused) for signature consistency with the other
    register_* functions — logging configuration is process-global, not
    app-instance-scoped. Safe to call more than once (e.g. once per test):
    configure_logging is itself idempotent.
    """
    configure_logging(settings.log_level, service=service, version=version)
    if uvicorn:
        for name in UVICORN_LOGGERS:
            logger = logging.getLogger(name)
            logger.handlers.clear()
            logger.propagate = True

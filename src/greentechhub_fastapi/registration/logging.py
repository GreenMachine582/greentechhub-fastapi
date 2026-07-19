"""register_logging — wires greentechhub_core's JSON logging into a service's startup.

Named `logging.py` inside a package that also imports the stdlib `logging`
indirectly (via greentechhub_core.logging) — safe for the same reason
greentechhub_core/logging/setup.py's own comment explains: Python 3's import
system is absolute-by-default (PEP 328), so a bare `import logging` elsewhere
always resolves to the stdlib module regardless of this file's location.
"""

from fastapi import FastAPI
from greentechhub_core.config import GTHBaseSettings
from greentechhub_core.logging import configure_logging


def register_logging(app: FastAPI, settings: GTHBaseSettings) -> None:
    """Configure the root logger for this service, per settings.log_level.

    `app` is accepted (and unused) for signature consistency with the other
    register_* functions — logging configuration is process-global, not
    app-instance-scoped, so there's nothing to attach to `app` here. Safe to call
    more than once (e.g. once per test): configure_logging is itself idempotent.
    """
    configure_logging(settings.log_level)

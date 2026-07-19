import logging

import pytest
from fastapi import FastAPI
from greentechhub_core.config import GTHBaseSettings

from greentechhub_fastapi import (
    register_core,
    register_exception_handlers,
    register_health,
    register_logging,
)


class _Settings(GTHBaseSettings):
    CORS_ALLOWED_ORIGINS: str = ""
    TRUSTED_PROXIES: str = ""


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    return _Settings()


def build_app(settings, *, checks=()):
    app = FastAPI()
    register_logging(app, settings)
    register_core(app, settings)
    register_health(app, checks=checks)
    register_exception_handlers(app)
    return app


@pytest.fixture(autouse=True)
def _restore_root_logger():
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    yield
    root.handlers = original_handlers
    root.setLevel(original_level)

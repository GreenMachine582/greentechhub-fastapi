"""register_logging(app, settings, service=, version=, uvicorn=): JSON lines
tagged with the service and version, and uvicorn's loggers through the same
handler on request."""

import json
import logging

import pytest
from fastapi import FastAPI
from greentechhub_core.config import GTHBaseSettings

from greentechhub_fastapi import register_logging
from greentechhub_fastapi.registration.logging import UVICORN_LOGGERS


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "s")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    return GTHBaseSettings(_env_file=None)


@pytest.fixture(autouse=True)
def _restore_uvicorn_loggers():
    saved = {name: (list(logging.getLogger(name).handlers), logging.getLogger(name).propagate)
             for name in UVICORN_LOGGERS}
    yield
    for name, (handlers, propagate) in saved.items():
        logger = logging.getLogger(name)
        logger.handlers[:] = handlers
        logger.propagate = propagate


def _last_json_line(capsys) -> dict:
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    return json.loads(lines[-1])


def test_lines_carry_the_service_and_version(settings, capsys):
    register_logging(FastAPI(), settings, service="pyfinbot", version="1.2.3")
    logging.getLogger("svc").info("hello")
    line = _last_json_line(capsys)
    assert line["message"] == "hello"
    assert line["service"] == "pyfinbot" and line["version"] == "1.2.3"


def test_without_them_the_fields_are_left_out(settings, capsys):
    register_logging(FastAPI(), settings)
    logging.getLogger("svc").info("plain")
    line = _last_json_line(capsys)
    assert line["message"] == "plain" and "service" not in line and "version" not in line


def test_uvicorn_loggers_go_through_the_json_handler(settings, capsys):
    for name in UVICORN_LOGGERS:
        logging.getLogger(name).addHandler(logging.StreamHandler())
        logging.getLogger(name).propagate = False
    register_logging(FastAPI(), settings, service="svc", uvicorn=True)
    for name in UVICORN_LOGGERS:
        assert logging.getLogger(name).handlers == [] and logging.getLogger(name).propagate
    logging.getLogger("uvicorn.error").info("Started server process")
    assert _last_json_line(capsys)["message"] == "Started server process"


def test_uvicorn_loggers_are_left_alone_by_default(settings):
    handler = logging.StreamHandler()
    logging.getLogger("uvicorn").addHandler(handler)
    register_logging(FastAPI(), settings)
    assert handler in logging.getLogger("uvicorn").handlers

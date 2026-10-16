"""query.lenient: optional_date / optional_datetime / optional_int /
optional_choice read a page's query-string filters leniently: missing,
blank or unreadable gives the default, never an error."""

from datetime import UTC, date, datetime, timedelta, timezone
from enum import StrEnum

import pytest

from greentechhub_fastapi.query import (
    optional_choice,
    optional_date,
    optional_datetime,
    optional_int,
)

TODAY = date(2026, 10, 16)


class Method(StrEnum):
    AVERAGE = "average"
    FIFO = "fifo"


@pytest.mark.parametrize("raw", [None, "", "   ", "not-a-date", "2026-13-01"])
def test_optional_date_falls_back(raw):
    assert optional_date(raw) is None
    assert optional_date(raw, TODAY) == TODAY


def test_optional_date_reads_iso():
    assert optional_date(" 2025-07-01 ", TODAY) == date(2025, 7, 1)


def test_optional_datetime_is_utc_without_an_offset():
    assert optional_datetime("2026-10-01T09:30:00") == datetime(2026, 10, 1, 9, 30, tzinfo=UTC)
    aest = optional_datetime("2026-10-01T09:30:00+10:00")
    assert aest.utcoffset() == timedelta(hours=10) and aest.tzinfo == timezone(timedelta(hours=10))
    assert optional_datetime("nope") is None and optional_datetime("", TODAY) == TODAY


@pytest.mark.parametrize("raw,expected", [
    ("42", 42), ("-7", -7), (" 3 ", 3), ("", None), ("4.5", None), ("x", None), (None, None)])
def test_optional_int(raw, expected):
    assert optional_int(raw) == expected


def test_optional_int_default():
    assert optional_int("x", 25) == 25


def test_optional_choice_with_an_enum():
    assert optional_choice("fifo", Method, Method.AVERAGE) is Method.FIFO
    assert optional_choice("lifo", Method, Method.AVERAGE) is Method.AVERAGE
    assert optional_choice(None, Method, Method.AVERAGE) is Method.AVERAGE


def test_optional_choice_with_strings():
    assert optional_choice("asx", ["asx", "nyse"], "asx") == "asx"
    assert optional_choice("ftse", ("asx", "nyse"), None) is None

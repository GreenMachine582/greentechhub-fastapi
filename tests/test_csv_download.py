"""downloads.csv_download / csv_value: a table's CSV export as a UTF-8
attachment with a BOM, and cell values that read back exactly."""

import asyncio
import csv
import io
from datetime import date, datetime
from decimal import Decimal

import httpx
from fastapi import FastAPI

from greentechhub_fastapi.downloads import BOM, csv_download, csv_value


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/items.csv")
    async def export():
        row = [csv_value(date(2025, 7, 1)), csv_value(Decimal("12.50")), "2025–26",
               'said "hi", twice']
        rows = [["Date", "Amount", "FY", "Notes"], row]
        return csv_download(rows, "items.csv")

    return app


def _get(app, url):
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(url)

    return asyncio.run(run())


def test_a_utf8_attachment_with_a_bom():
    resp = _get(_app(), "/items.csv")
    assert resp.headers["content-type"] == "text/csv; charset=utf-8"
    assert resp.headers["content-disposition"] == 'attachment; filename="items.csv"'
    assert resp.content.startswith(b"\xef\xbb\xbf")
    assert resp.text.startswith(BOM + "Date,Amount,FY,Notes")


def test_the_rows_read_back_exactly():
    text = _get(_app(), "/items.csv").content.decode("utf-8-sig")
    assert list(csv.reader(io.StringIO(text))) == [
        ["Date", "Amount", "FY", "Notes"],
        ["2025-07-01", "12.5", "2025–26", 'said "hi", twice'],
    ]


def test_csv_value():
    assert csv_value(None) == ""
    assert csv_value(Decimal("12.50")) == "12.5"
    assert csv_value(Decimal("1E+2")) == "100"
    assert csv_value(Decimal("0.000001234")) == "0.000001234"
    assert csv_value(date(2025, 7, 1)) == "2025-07-01"
    assert csv_value(datetime(2025, 7, 1, 9, 30)) == "2025-07-01T09:30:00"
    assert csv_value(3) == "3" and csv_value("x") == "x"

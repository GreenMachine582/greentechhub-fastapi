"""downloads — a CSV file as a download: what a table's "Export CSV" link
(greentechhub-ui's TableState.export_url) answers with.

    @router.get("/transactions.csv")
    async def export(...):
        rows = [HEADER, *([csv_value(t.date), csv_value(t.amount), t.notes] for t in items)]
        return csv_download(rows, "transactions.csv")
"""

import csv
import io
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from starlette.responses import Response

#: A UTF-8 byte-order mark. Excel opens a CSV without one as Windows-1252, so
#: UTF-8 text such as an en dash ("2025–26") shows up as "2025â€“26". With it,
#: Excel, Numbers and LibreOffice all read UTF-8; pandas reads it with
#: encoding="utf-8-sig".
BOM = "﻿"


def csv_download(rows: Iterable[Iterable[Any]], filename: str) -> Response:
    """`rows` (the header first) as a UTF-8 CSV attachment named `filename`,
    with a BOM so spreadsheets read it as UTF-8."""
    buffer = io.StringIO()
    buffer.write(BOM)
    csv.writer(buffer).writerows(rows)
    return Response(buffer.getvalue(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
    })


def csv_value(value: Any) -> str:
    """`value` as a CSV cell: "" for None, a Decimal at full precision with
    trailing zeros trimmed and never in E-notation (12.50 → "12.5",
    1E+2 → "100"), a date or datetime in ISO format, anything else str()."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{value.normalize():f}"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)

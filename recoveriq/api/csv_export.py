"""Export CSV compatible Excel (Windows, paramètres régionaux suisses / français).

Séparateur « ; », point décimal, encodage UTF-8 avec BOM (sinon Excel lit les
accents en Windows-1252).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from fastapi.responses import Response


def csv_response(filename: str, columns: Sequence[tuple[str, str]], rows: Iterable[dict[str, Any]]) -> Response:
    """``columns`` = [(clé dans la ligne, en-tête affiché)]."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow([header for _, header in columns])
    for row in rows:
        writer.writerow(["" if row.get(key) is None else row.get(key) for key, _ in columns])
    content = "﻿" + buffer.getvalue()
    name = f"recoveriq_{filename}_{date.today().isoformat()}.csv"
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )

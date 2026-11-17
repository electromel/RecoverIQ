"""Matériel : montres ayant enregistré les activités.

La liste des activités Garmin ne donne que l'identifiant de la montre (``deviceId``) ;
son nom vient des réponses « statut d'entraînement » (table ``device``). Certaines
activités anciennes n'indiquent aucune montre, et l'identifiant 0 ne désigne pas
de montre réelle.
"""

from __future__ import annotations

import sqlite3
from typing import Any


def device_label(device_id: int | None, name: str | None) -> str:
    if device_id is None:
        return "Non indiquée par Garmin"
    if device_id == 0:
        return "Aucune montre (identifiant 0)"
    return name or "Modèle inconnu"


def devices_view(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Une ligne par montre (et par cas sans montre), de la plus ancienne à la plus récente."""
    rows = [dict(r) for r in conn.execute(
        "SELECT a.device_id, d.name, MIN(a.date) AS first_date, MAX(a.date) AS last_date, "
        "COUNT(*) AS activities, SUM(a.duration_s) AS duration_s, SUM(a.distance_m) AS distance_m, "
        "SUM(a.elev_gain_m) AS elev_gain_m "
        "FROM activity a LEFT JOIN device d ON d.device_id = a.device_id "
        "GROUP BY a.device_id ORDER BY first_date, a.device_id")]
    types: dict[Any, list[dict[str, Any]]] = {}
    for r in conn.execute(
        "SELECT device_id, type, COUNT(*) AS n FROM activity GROUP BY device_id, type ORDER BY n DESC, type"
    ):
        types.setdefault(r["device_id"], []).append({"type": r["type"], "count": r["n"]})
    for r in rows:
        r["label"] = device_label(r["device_id"], r["name"])
        r["types"] = types.get(r["device_id"], [])
    # Montres connues sans activité enregistrée (portées seulement au quotidien).
    for r in conn.execute(
        "SELECT device_id, name, date FROM device WHERE device_id NOT IN "
        "(SELECT device_id FROM activity WHERE device_id IS NOT NULL)"
    ):
        rows.append({
            "device_id": r["device_id"], "name": r["name"], "label": device_label(r["device_id"], r["name"]),
            "first_date": None, "last_date": None, "activities": 0, "duration_s": None,
            "distance_m": None, "elev_gain_m": None, "types": [],
        })
    return rows


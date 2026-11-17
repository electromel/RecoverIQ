"""Vue détaillée d'un jour : la veille, le jour et le lendemain.

Deux niveaux de détail :

* **journalier** : la valeur de chaque indicateur du catalogue pour les 3 jours ;
* **intra-journalier** : les mesures fines déjà présentes dans les réponses brutes
  Garmin (``raw_response``), sans nouvel appel réseau. Le sommeil fournit la nuit
  minute par minute (FC, stress, Body Battery, VFC, SpO2, respiration, phases) ;
  les appels « FC de la journée » et « stress de la journée » couvrent les 24 h
  (FC toutes les 2 min, stress et Body Battery toutes les 3 min) ; l'appel Body
  Battery par plage ajoute quelques points par jour quand ce détail manque.

Les instants sont renvoyés en millisecondes epoch (UTC) ; le navigateur les affiche
à l'heure locale. Valeurs négatives = « pas de mesure » chez Garmin : écartées.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any

from recoveriq.analytics.catalog import SERIES
from recoveriq.analytics.devices import device_label

Point = list[float]   # [epoch_ms, valeur]


def _epoch_ms(value: Any) -> int | None:
    """Horodatage Garmin (ms epoch ou ISO GMT sans fuseau) → ms epoch."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    if isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace(" ", "T").rstrip("Z"))
        except ValueError:
            return None
        return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
    return None


def _value(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value >= 0 else None


def _points(items: Any, time_key: str, value_key: str) -> list[Point]:
    out: list[Point] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        t, v = _epoch_ms(item.get(time_key)), _value(item.get(value_key))
        if t is not None and v is not None:
            out.append([t, v])
    return out


def _payloads(conn: sqlite3.Connection, fetcher: str, first: str, last: str) -> list[Any]:
    rows = conn.execute(
        "SELECT payload FROM raw_response WHERE fetcher = ? AND outcome = 'ok' "
        "AND start_date <= ? AND end_date >= ? ORDER BY start_date",
        (fetcher, last, first),
    ).fetchall()
    out = []
    for r in rows:
        try:
            out.append(json.loads(r["payload"]))
        except (TypeError, ValueError):
            continue
    return out


def _merge(series: list[list[Point]]) -> list[Point]:
    """Fusionne plusieurs sources, trie par instant et supprime les doublons d'instant."""
    seen: dict[int, float] = {}
    for points in series:
        for t, v in points:
            seen.setdefault(int(t), v)
    return [[t, seen[t]] for t in sorted(seen)]


def _prefer(primary: list[list[Point]], others: list[list[Point]]) -> list[Point]:
    """Fusionne ``others`` dans ``primary`` hors des plages déjà couvertes par ``primary``."""
    windows = [(pts[0][0], pts[-1][0]) for pts in (sorted(p) for p in primary) if pts]
    kept = [[pt for pt in pts if not any(a <= pt[0] <= b for a, b in windows)] for pts in others]
    return _merge(primary + kept)


def _pairs(items: Any, value_index: int) -> list[Point]:
    """Tableaux Garmin ``[[epoch_ms, …, valeur, …], …]`` → points."""
    out: list[Point] = []
    for v in items if isinstance(items, list) else []:
        if isinstance(v, list) and len(v) > value_index:
            t, val = _epoch_ms(v[0]), _value(v[value_index])
            if t is not None and val is not None:
                out.append([t, val])
    return out


def _sleep_stages(levels: Any) -> list[dict[str, Any]]:
    """Phases de sommeil : 0 profond, 1 léger, 2 paradoxal, 3 éveil."""
    out = []
    for item in levels if isinstance(levels, list) else []:
        if not isinstance(item, dict):
            continue
        start, end = _epoch_ms(item.get("startGMT")), _epoch_ms(item.get("endGMT"))
        level = _value(item.get("activityLevel"))
        if start is not None and end is not None and level is not None:
            out.append({"start": start, "end": end, "level": int(round(level))})
    return sorted(out, key=lambda s: s["start"])


def intraday(conn: sqlite3.Connection, first: date, last: date) -> dict[str, Any]:
    """Séries intra-journalières couvrant [first, last] (plus la nuit qui suit ``last``)."""
    lo, hi = first.isoformat(), (last + timedelta(days=1)).isoformat()
    hr, stress, bb, hrv, spo2, resp, stages, nights = [], [], [], [], [], [], [], []

    # Journée complète : FC (toutes les 2 min), stress et Body Battery (toutes les 3 min).
    # Là où elle existe, elle prime sur les autres sources (horodatages décalés).
    full: dict[str, list[list[Point]]] = {"heart_rate": [], "stress": [], "body_battery": []}
    for p in _payloads(conn, "heart_rates", lo, hi):
        if isinstance(p, dict):
            full["heart_rate"].append(_pairs(p.get("heartRateValues"), 1))
    for p in _payloads(conn, "stress", lo, hi):
        if isinstance(p, dict):
            full["stress"].append(_pairs(p.get("stressValuesArray"), 1))
            # [instant, statut, niveau, version]
            full["body_battery"].append(_pairs(p.get("bodyBatteryValuesArray"), 2))

    # Sommeil : la réponse du jour J décrit la nuit qui se termine le matin de J.
    for p in _payloads(conn, "sleep", lo, hi):
        if not isinstance(p, dict):
            continue
        hr.append(_points(p.get("sleepHeartRate"), "startGMT", "value"))
        stress.append(_points(p.get("sleepStress"), "startGMT", "value"))
        bb.append(_points(p.get("sleepBodyBattery"), "startGMT", "value"))
        hrv.append(_points(p.get("hrvData"), "startGMT", "value"))
        spo2.append(_points(p.get("wellnessEpochSPO2DataDTOList"), "epochTimestamp", "spo2Reading"))
        resp.append(_points(p.get("wellnessEpochRespirationDataDTOList"), "startTimeGMT", "respirationValue"))
        stages += _sleep_stages(p.get("sleepLevels"))
        dto = p.get("dailySleepDTO") if isinstance(p.get("dailySleepDTO"), dict) else {}
        start = _epoch_ms(dto.get("sleepStartTimestampGMT"))
        end = _epoch_ms(dto.get("sleepEndTimestampGMT"))
        if start and end:
            nights.append({"start": start, "end": end, "date": dto.get("calendarDate")})

    # Body Battery de la journée (appel par plage : liste de jours).
    for p in _payloads(conn, "body_battery", lo, hi):
        for day in p if isinstance(p, list) else []:
            if not isinstance(day, dict) or not (lo <= str(day.get("date", ""))[:10] <= hi):
                continue
            bb.append(_pairs(day.get("bodyBatteryValuesArray"), 1))

    return {
        "heart_rate": _prefer(full["heart_rate"], hr), "stress": _prefer(full["stress"], stress),
        "body_battery": _prefer(full["body_battery"], bb),
        "hrv": _merge(hrv), "spo2": _merge(spo2), "respiration": _merge(resp),
        "sleep_stages": stages, "nights": sorted(nights, key=lambda n: n["start"]),
        # Séries couvrant aussi la journée (pas seulement la nuit).
        "day_series": sorted(k for k, v in full.items() if any(v)),
    }


def daily_values(conn: sqlite3.Connection, dates: list[str]) -> list[dict[str, Any]]:
    """Valeur de chaque indicateur du catalogue pour chacune des dates."""
    out = []
    for s in SERIES:
        marks = ",".join("?" * len(dates))
        rows = conn.execute(
            f"SELECT date, {s.column} AS v FROM {s.table} WHERE date IN ({marks})", dates,
        ).fetchall()
        found = {r["date"]: r["v"] for r in rows}
        values = [None if found.get(d) is None else float(found[d]) * s.scale for d in dates]
        out.append({"key": s.key, "label": s.label, "unit": s.unit, "group": s.group,
                    "decimals": s.decimals, "description": s.description,
                    "values": values})
    return out


def activities(conn: sqlite3.Connection, first: str, last: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT a.activity_id, a.date, a.start_local, a.type, a.name, a.duration_s, a.distance_m, a.elev_gain_m, "
        "a.avg_hr, a.max_hr, a.calories, a.training_load, a.aerobic_te, a.anaerobic_te, a.device_id, "
        "d.name AS device_name "
        "FROM activity a LEFT JOIN device d ON d.device_id = a.device_id "
        "WHERE a.date BETWEEN ? AND ? ORDER BY a.start_local", (first, last),
    ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["device"] = device_label(item.pop("device_id"), item.pop("device_name"))
        out.append(item)
    return out


def day_devices(conn: sqlite3.Connection, dates: list[str], acts: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    """Montres de chaque jour : celles des activités, et la montre principale du statut d'entraînement.

    Les deux peuvent différer (changement de montre : Garmin désigne déjà la nouvelle
    comme principale alors qu'une activité est encore enregistrée avec l'ancienne).
    """
    out: dict[str, dict[str, list[str]]] = {}
    for d in dates:
        names: list[str] = []
        for payload in _payloads(conn, "training_status", d, d):
            recorded = payload.get("mostRecentTrainingStatus", {}).get("recordedDevices")                 if isinstance(payload, dict) and isinstance(payload.get("mostRecentTrainingStatus"), dict) else None
            for dev in recorded if isinstance(recorded, list) else []:
                name = dev.get("deviceName") if isinstance(dev, dict) else None
                if isinstance(name, str) and name and not name.startswith("other.") and name not in names:
                    names.append(name)
        out[d] = {
            "activities": list(dict.fromkeys(a["device"] for a in acts if a["date"] == d)),
            "primary": names,
        }
    return out


def day_view(conn: sqlite3.Connection, day: date) -> dict[str, Any]:
    first, last = day - timedelta(days=1), day + timedelta(days=1)
    dates = [(first + timedelta(days=i)).isoformat() for i in range(3)]
    acts = activities(conn, dates[0], dates[-1])
    return {
        "date": day.isoformat(),
        "dates": dates,
        "daily": daily_values(conn, dates),
        "activities": acts,
        "devices": day_devices(conn, dates, acts),
        "intraday": intraday(conn, first, last),
    }

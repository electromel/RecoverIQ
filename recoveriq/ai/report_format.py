"""Format JSON imposé aux LLM, et validation tolérante de leurs réponses.

Chaque modèle doit répondre par un objet :

.. code-block:: json

    {
      "highlights":  ["…"],
      "trends":      [{"metric": "hrv", "direction": "up|down|stable", "comment": "…"}],
      "alerts":      [{"metric": "sleep_duration", "severity": "low|medium|high", "title": "…", "detail": "…"}],
      "suggestions": [{"title": "…", "detail": "…"}]          // exactement 3
    }

``metric`` reprend les clés du catalogue (ou ``general``) : c'est ce qui permet de
comparer les rapports de plusieurs modèles sans interpréter leur texte libre.
La validation corrige ce qui peut l'être (synonymes français, clé inconnue →
``general``) et ne rejette que les réponses inexploitables.
"""

from __future__ import annotations

import json
import re
from typing import Any

from recoveriq.analytics.catalog import SERIES

SEVERITIES = ("low", "medium", "high")
DIRECTIONS = ("up", "down", "stable")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}

# Clés « metric » acceptées : séries du catalogue + thèmes transverses.
EXTRA_TOPICS = {
    "general": "Général",
    "training_load": "Charge d'entraînement",
    "activities": "Activités",
}
METRIC_LABELS: dict[str, str] = {s.key: s.label for s in SERIES} | EXTRA_TOPICS

_SEVERITY_SYNONYMS = {
    "low": "low", "faible": "low", "basse": "low", "info": "low", "mineure": "low",
    "medium": "medium", "moderate": "medium", "moyenne": "medium", "modérée": "medium", "moderee": "medium",
    "high": "high", "élevée": "high", "elevee": "high", "haute": "high", "forte": "high", "critical": "high",
}
_DIRECTION_SYNONYMS = {
    "up": "up", "hausse": "up", "increase": "up", "increasing": "up", "rising": "up",
    "down": "down", "baisse": "down", "decrease": "down", "decreasing": "down", "falling": "down",
    "stable": "stable", "flat": "stable", "steady": "stable",
}

MAX_TEXT = 600
MAX_ITEMS = 10
SUGGESTION_COUNT = 3


class ReportFormatError(ValueError):
    pass


def extract_json(text: str) -> Any:
    """Décode le JSON d'une réponse, même entouré de ```json … ``` ou de texte."""
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.IGNORECASE)
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ReportFormatError("la réponse ne contient pas d'objet JSON")
    try:
        return json.loads(cleaned[start:end + 1])
    except ValueError as exc:
        raise ReportFormatError(f"JSON invalide ({exc.msg})") from exc


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:MAX_TEXT]


def _metric(value: Any) -> str:
    key = str(value or "").strip()
    return key if key in METRIC_LABELS else "general"


def _items(obj: dict[str, Any], key: str) -> list[Any]:
    value = obj.get(key)
    return value[:MAX_ITEMS] if isinstance(value, list) else []


def _suggestions(raw: list[Any]) -> list[dict[str, str]]:
    out = []
    for s in raw:
        if isinstance(s, str) and _text(s):
            out.append({"title": _text(s), "detail": ""})
        elif isinstance(s, dict) and _text(s.get("title") or s.get("detail")):
            out.append({"title": _text(s.get("title") or s.get("detail")),
                        "detail": _text(s.get("detail")) if s.get("title") else ""})
    return out


def validate_report(data: Any) -> tuple[dict[str, Any], list[str]]:
    """Normalise un rapport individuel. Renvoie (rapport, avertissements)."""
    if not isinstance(data, dict):
        raise ReportFormatError("la réponse n'est pas un objet JSON")
    warnings: list[str] = []

    highlights = [_text(h) for h in _items(data, "highlights") if _text(h)]

    trends = []
    for t in _items(data, "trends"):
        if not isinstance(t, dict):
            continue
        direction = _DIRECTION_SYNONYMS.get(str(t.get("direction", "")).strip().lower())
        if direction is None:
            continue
        trends.append({"metric": _metric(t.get("metric")), "direction": direction,
                       "comment": _text(t.get("comment"))})

    alerts = []
    for a in _items(data, "alerts"):
        if not isinstance(a, dict) or not _text(a.get("title") or a.get("detail")):
            continue
        severity = _SEVERITY_SYNONYMS.get(str(a.get("severity", "")).strip().lower(), "medium")
        alerts.append({"metric": _metric(a.get("metric")), "severity": severity,
                       "title": _text(a.get("title") or a.get("detail")), "detail": _text(a.get("detail"))})

    suggestions = _suggestions(_items(data, "suggestions"))
    if not (highlights or trends or alerts or suggestions):
        raise ReportFormatError("aucune des rubriques attendues n'est présente")
    if len(suggestions) != SUGGESTION_COUNT:
        warnings.append(f"{len(suggestions)} suggestion(s) au lieu de {SUGGESTION_COUNT}")
    return ({"highlights": highlights, "trends": trends, "alerts": alerts,
             "suggestions": suggestions[:SUGGESTION_COUNT]}, warnings)


def parse_report(text: str) -> tuple[dict[str, Any], list[str]]:
    return validate_report(extract_json(text))


def validate_synthesis(data: Any) -> dict[str, Any]:
    """Synthèse de l'agrégateur : {summary, consensus[], divergences[], suggestions[3]}."""
    if not isinstance(data, dict) or not _text(data.get("summary")):
        raise ReportFormatError("synthèse sans résumé")
    return {
        "summary": _text(data.get("summary")),
        "consensus": [_text(c) for c in _items(data, "consensus") if _text(c)],
        "divergences": [_text(d) for d in _items(data, "divergences") if _text(d)],
        "suggestions": _suggestions(_items(data, "suggestions"))[:SUGGESTION_COUNT],
    }

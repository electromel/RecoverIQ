"""Comparaison déterministe de plusieurs rapports (sans LLM).

Toujours calculée : elle sert de **repli** quand l'agrégateur échoue ou n'est pas
configuré, et elle complète la synthèse de l'agrégateur par des tableaux factuels.
La comparaison s'appuie sur le champ ``metric`` imposé dans le format de réponse.

* **consensus** : alerte posée sur un même indicateur par au moins 2 modèles et
  au moins la moitié des modèles ayant répondu ;
* **alerte isolée** : posée par un seul modèle (quand plusieurs ont répondu) ;
* **écart de sévérité** : même indicateur, sévérités différentes ;
* **tendance divergente** : même indicateur, l'un voit une hausse, l'autre une baisse.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from recoveriq.ai.report_format import METRIC_LABELS, SEVERITY_RANK


def compare_reports(reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    n = len(reports)
    alerts_by_metric: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for pid, rep in reports.items():
        for a in rep["alerts"]:
            current = alerts_by_metric[a["metric"]].get(pid)
            # Un modèle peut poser plusieurs alertes sur un indicateur : on garde la plus sévère.
            if current is None or SEVERITY_RANK[a["severity"]] > SEVERITY_RANK[current["severity"]]:
                alerts_by_metric[a["metric"]][pid] = a

    consensus, isolated, severity_gaps = [], [], []
    for metric, by_provider in alerts_by_metric.items():
        entry = {
            "metric": metric, "label": METRIC_LABELS.get(metric, metric),
            "providers": {pid: {"severity": a["severity"], "title": a["title"]} for pid, a in by_provider.items()},
            "max_severity": max((a["severity"] for a in by_provider.values()), key=SEVERITY_RANK.get),
        }
        count = len(by_provider)
        if count >= 2 and count * 2 >= n:
            consensus.append(entry)
        elif count == 1 and n >= 2:
            isolated.append(entry)
        if count >= 2 and len({a["severity"] for a in by_provider.values()}) > 1:
            severity_gaps.append(entry)

    trends_by_metric: dict[str, dict[str, str]] = defaultdict(dict)
    for pid, rep in reports.items():
        for t in rep["trends"]:
            trends_by_metric[t["metric"]].setdefault(pid, t["direction"])
    trend_rows = []
    for metric, by_provider in trends_by_metric.items():
        directions = set(by_provider.values())
        trend_rows.append({
            "metric": metric, "label": METRIC_LABELS.get(metric, metric), "providers": by_provider,
            "agreement": "conflict" if {"up", "down"} <= directions
            else ("agree" if len(directions) == 1 and len(by_provider) >= 2 else "partial"),
        })

    by_severity = lambda e: (-SEVERITY_RANK[e["max_severity"]], e["label"])  # noqa: E731
    return {
        "providers": list(reports),
        "consensus_alerts": sorted(consensus, key=by_severity),
        "isolated_alerts": sorted(isolated, key=by_severity),
        "severity_differences": sorted(severity_gaps, key=by_severity),
        "trends": sorted(trend_rows, key=lambda t: (t["agreement"] != "conflict", t["label"])),
    }

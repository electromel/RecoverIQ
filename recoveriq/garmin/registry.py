"""Registre des appels Garmin (« fetchers »).

Point d'extension unique : ajouter un indicateur = déclarer un :class:`Fetcher`
ici, écrire son parser dans :mod:`recoveriq.garmin.parsers` et, si besoin, sa table
dans ``schema.sql``. Le moteur de synchronisation n'a pas à être modifié.

Choix d'appels (vérifiés sur garminconnect 0.3.2) : 5 appels journaliers suffisent
à couvrir tous les indicateurs journaliers, car le résumé journalier et les données de sommeil
contiennent déjà stress, intensité, FC repos, respiration et SpO2. Cela divise
par deux la durée de l'import historique par rapport à un appel par indicateur.
Deux appels de plus conservent la FC et le stress minute par minute de la journée.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from garminconnect import Garmin

from recoveriq.garmin import parsers


class Scope(Enum):
    DAILY = "daily"   # un appel par jour
    RANGE = "range"   # un appel par plage de dates (blocs de 30 jours)


@dataclass(frozen=True)
class Fetcher:
    name: str
    label: str
    scope: Scope
    # DAILY : call(garmin, date) ; RANGE : call(garmin, start, end)
    call: Callable[..., Any]
    parser: Callable[..., parsers.Rows]
    # Variante journalière utilisée en synchro incrémentale, quand la plage
    # ne fournit qu'une approximation (ex. Endurance Score hebdomadaire).
    incremental_daily: Fetcher | None = None
    # Appel conservé uniquement en brut (aucune table normalisée) : indique si la
    # réponse contient des mesures, pour l'arrêt de l'import sur une série vide.
    has_detail: Callable[[Any], bool] | None = None


ENDURANCE_DAY = Fetcher(
    "endurance_day", "Endurance Score (jour)", Scope.DAILY,
    lambda g, d: g.get_endurance_score(d), parsers.parse_endurance_day,
)

FETCHERS: tuple[Fetcher, ...] = (
    # --- Journaliers -----------------------------------------------------------
    Fetcher("user_summary", "Résumé journalier", Scope.DAILY,
            lambda g, d: g.get_user_summary(d), parsers.parse_user_summary),
    Fetcher("hrv", "VFC", Scope.DAILY,
            lambda g, d: g.get_hrv_data(d), parsers.parse_hrv),
    Fetcher("training_status", "Statut et charge d'entraînement", Scope.DAILY,
            lambda g, d: g.get_training_status(d), parsers.parse_training_status),
    Fetcher("sleep", "Sommeil", Scope.DAILY,
            lambda g, d: g.get_sleep_data(d), parsers.parse_sleep),
    Fetcher("training_readiness", "Training Readiness", Scope.DAILY,
            lambda g, d: g.get_training_readiness(d), parsers.parse_training_readiness),
    # Détail intra-journalier, conservé en brut pour la vue « détail sur 3 jours ».
    # Garmin ne le sert que pendant quelques mois (≈ 4,5) : il faut l'enregistrer à temps.
    Fetcher("heart_rates", "FC de la journée", Scope.DAILY,
            lambda g, d: g.get_heart_rates(d), parsers.no_rows,
            has_detail=lambda p: parsers.has_values(p, "heartRateValues")),
    Fetcher("stress", "Stress de la journée", Scope.DAILY,
            lambda g, d: g.get_stress_data(d), parsers.no_rows,
            has_detail=lambda p: parsers.has_values(p, "stressValuesArray")),
    # --- Par plage -------------------------------------------------------------
    Fetcher("body_battery", "Body Battery", Scope.RANGE,
            lambda g, s, e: g.get_body_battery(s, e), parsers.parse_body_battery_range),
    Fetcher("hill_score", "Hill Score", Scope.RANGE,
            lambda g, s, e: g.get_hill_score(s, e), parsers.parse_hill_range),
    Fetcher("endurance_score", "Endurance Score", Scope.RANGE,
            lambda g, s, e: g.get_endurance_score(s, e), parsers.parse_endurance_range,
            incremental_daily=ENDURANCE_DAY),
    Fetcher("activities", "Activités", Scope.RANGE,
            lambda g, s, e: g.get_activities_by_date(s, e), parsers.parse_activities),
)

DAILY_FETCHERS = tuple(f for f in FETCHERS if f.scope is Scope.DAILY)
RANGE_FETCHERS = tuple(f for f in FETCHERS if f.scope is Scope.RANGE)


def find_earliest_activity_date(garmin: Garmin) -> str | None:
    """Date de la plus ancienne activité du compte (point de départ de l'historique)."""
    count = garmin.count_activities()
    if not isinstance(count, int) or count <= 0:
        return None
    oldest = garmin.get_activities(start=count - 1, limit=1)
    if isinstance(oldest, list) and oldest:
        start_local = oldest[0].get("startTimeLocal")
        if isinstance(start_local, str) and len(start_local) >= 10:
            return start_local[:10]
    return None

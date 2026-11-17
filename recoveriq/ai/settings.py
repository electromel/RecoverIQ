"""Réglages de l'analyse IA.

* réglages non secrets (activation, modèle, adresse, tarifs, planification) :
  table ``app_setting``, clé ``ai.settings`` (JSON) ;
* clés API : Gestionnaire d'identifiants Windows via ``keyring``, nom ``ai:<fournisseur>``.
  Elles ne sont jamais renvoyées par l'API web, seulement leur présence.

Tarifs : prix en dollars US par million de jetons (entrée / sortie), saisis par
l'utilisateur depuis la page tarifs du fournisseur. Sans tarif, le coût n'est pas
estimé (les jetons restent comptés).
"""

from __future__ import annotations

import copy
import sqlite3
from typing import Any

from recoveriq import secrets_store
from recoveriq.ai.providers import PROVIDER_CLASSES, ProviderConfig
from recoveriq.db import repository as repo

SETTINGS_KEY = "ai.settings"
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ANALYSIS_PERIODS = (7, 14, 28, 90, 365)
AGGREGATOR_AUTO = "auto"   # premier fournisseur (dans l'ordre affiché) ayant rendu un rapport valide
AGGREGATOR_NONE = ""       # comparaison simple uniquement


def _defaults() -> dict[str, Any]:
    return {
        "providers": {
            cls.id: {
                "enabled": False,
                "model": cls.default_model,
                "base_url": cls.default_base_url or "",
                # Serveur personnalisé : souvent local (Ollama) donc gratuit par défaut.
                "price_in": 0.0 if cls.id == "custom" else None,
                "price_out": 0.0 if cls.id == "custom" else None,
            }
            for cls in PROVIDER_CLASSES
        },
        "aggregator": AGGREGATOR_AUTO,
        "timeout_s": 120,
        "weekly": {"enabled": True, "day": "mon", "time": "07:30", "period_days": 7},
    }


def load(conn: sqlite3.Connection) -> dict[str, Any]:
    """Réglages complets (valeurs par défaut + valeurs enregistrées)."""
    settings = _defaults()
    stored = repo.get_setting(conn, SETTINGS_KEY, {}) or {}
    for pid, values in (stored.get("providers") or {}).items():
        if pid in settings["providers"]:
            settings["providers"][pid].update(values)
    for key in ("aggregator", "timeout_s"):
        if key in stored:
            settings[key] = stored[key]
    settings["weekly"].update(stored.get("weekly") or {})
    return settings


def save(conn: sqlite3.Connection, settings: dict[str, Any]) -> None:
    repo.set_setting(conn, SETTINGS_KEY, settings)


def update_provider(conn: sqlite3.Connection, pid: str, patch: dict[str, Any]) -> dict[str, Any]:
    settings = load(conn)
    settings["providers"][pid].update(patch)
    save(conn, settings)
    return settings


def update_global(conn: sqlite3.Connection, patch: dict[str, Any]) -> dict[str, Any]:
    settings = load(conn)
    for key, value in patch.items():
        if key == "weekly":
            settings["weekly"].update(value)
        else:
            settings[key] = value
    save(conn, settings)
    return settings


# --- Clés API (trousseau Windows) --------------------------------------------------

def _secret_name(pid: str) -> str:
    return f"ai:{pid}"


def get_key(pid: str) -> str | None:
    return secrets_store.get_secret(_secret_name(pid))


def set_key(pid: str, key: str) -> None:
    secrets_store.set_secret(_secret_name(pid), key.strip())


def delete_key(pid: str) -> None:
    secrets_store.delete_secret(_secret_name(pid))


def provider_config(settings: dict[str, Any], pid: str, overrides: dict[str, Any] | None = None) -> ProviderConfig:
    p = {**settings["providers"][pid], **(overrides or {})}
    key = (overrides or {}).get("api_key") or get_key(pid)
    return ProviderConfig(model=(p.get("model") or "").strip(), api_key=key,
                          base_url=(p.get("base_url") or "").strip() or None,
                          timeout_s=float(settings["timeout_s"]))


def public_view(settings: dict[str, Any]) -> dict[str, Any]:
    """Réglages pour l'interface : métadonnées des fournisseurs + présence des clés (jamais leur valeur)."""
    view = copy.deepcopy(settings)
    view["provider_list"] = [
        {"id": cls.id, "label": cls.label, "needs_key": cls.needs_key, "needs_base_url": cls.needs_base_url,
         "default_base_url": cls.default_base_url, "key_help": cls.key_help,
         "key_url": cls.key_url, "pricing_url": cls.pricing_url,
         "has_key": bool(get_key(cls.id)), **settings["providers"][cls.id]}
        for cls in PROVIDER_CLASSES
    ]
    del view["providers"]
    view["weekdays"] = list(WEEKDAYS)
    view["periods"] = list(ANALYSIS_PERIODS)
    return view


def estimate_cost(settings: dict[str, Any], pid: str, input_tokens: int | None,
                  output_tokens: int | None) -> float | None:
    p = settings["providers"].get(pid) or {}
    price_in, price_out = p.get("price_in"), p.get("price_out")
    if price_in is None or price_out is None or input_tokens is None or output_tokens is None:
        return None
    return round((input_tokens * float(price_in) + output_tokens * float(price_out)) / 1_000_000, 6)

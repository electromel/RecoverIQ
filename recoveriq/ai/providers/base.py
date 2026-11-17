"""Classe de base des fournisseurs LLM.

Chaque adaptateur ne traduit que le format de requête / réponse de son API.
Le transport HTTP (``httpx``), la gestion des délais et la traduction des erreurs
sont communs. Aucun SDK propriétaire : moins de dépendances, et un comportement
identique pour tous les fournisseurs.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(frozen=True)
class ProviderConfig:
    """Réglages d'un fournisseur (la clé vient du trousseau, jamais de la base)."""

    model: str
    api_key: str | None = None
    base_url: str | None = None
    timeout_s: float = 120.0


@dataclass
class Completion:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_ms: int = 0


@dataclass
class TestResult:
    ok: bool
    message: str
    models: list[str] = field(default_factory=list)
    duration_ms: int = 0


class ProviderError(Exception):
    """Erreur lisible par l'utilisateur (clé refusée, modèle inconnu, quota…)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ProviderTimeout(ProviderError):
    pass


def _http_message(status: int, detail: str) -> str:
    hints = {
        400: "requête refusée",
        401: "clé API refusée",
        403: "accès refusé (clé ou droits du compte)",
        404: "modèle ou adresse introuvable",
        429: "quota ou limite de débit atteint",
    }
    hint = hints.get(status, "erreur du service" if status >= 500 else "erreur")
    return f"HTTP {status} : {hint}" + (f" — {detail}" if detail else "")


class LLMProvider(ABC):
    """Contrat commun : produire un texte à partir d'un prompt système + utilisateur."""

    id: str = ""
    label: str = ""
    needs_key: bool = True
    needs_base_url: bool = False
    default_model: str = ""
    default_base_url: str | None = None
    key_help: str = ""
    key_url: str | None = None       # page de création des clés API
    pricing_url: str | None = None   # page des tarifs (prix par million de jetons)

    def __init__(self, client: httpx.Client | None = None) -> None:
        # Client injectable pour les tests (httpx.MockTransport).
        self._client = client

    # --- À implémenter par chaque adaptateur ---------------------------------

    @abstractmethod
    def _complete(self, cfg: ProviderConfig, system: str, user: str) -> Completion:
        """Appel de génération ; lève ProviderError en cas d'échec."""

    @abstractmethod
    def _list_models(self, cfg: ProviderConfig) -> list[str]:
        """Modèles accessibles avec cette clé (sert aussi de test de connexion gratuit)."""

    # --- API publique ----------------------------------------------------------

    def complete(self, cfg: ProviderConfig, system: str, user: str) -> Completion:
        self._check(cfg)
        if not cfg.model:
            raise ProviderError("aucun modèle choisi")
        start = time.monotonic()
        result = self._complete(cfg, system, user)
        result.duration_ms = int((time.monotonic() - start) * 1000)
        if not result.text.strip():
            raise ProviderError("réponse vide")
        return result

    def test(self, cfg: ProviderConfig) -> TestResult:
        """Vérifie la clé et l'adresse en listant les modèles (aucun jeton consommé)."""
        start = time.monotonic()
        try:
            self._check(cfg)
            models = sorted(set(self._list_models(cfg)))
        except ProviderError as exc:
            return TestResult(False, str(exc), duration_ms=int((time.monotonic() - start) * 1000))
        ms = int((time.monotonic() - start) * 1000)
        if cfg.model and models and cfg.model not in models:
            return TestResult(False, f"Connexion OK, mais le modèle « {cfg.model} » n'est pas proposé "
                                     f"par ce compte.", models, ms)
        return TestResult(True, f"Connexion OK ({len(models)} modèle(s) disponible(s)).", models, ms)

    # --- Outils pour les adaptateurs -----------------------------------------

    def _check(self, cfg: ProviderConfig) -> None:
        if self.needs_key and not cfg.api_key:
            raise ProviderError("clé API manquante")
        if self.needs_base_url and not (cfg.base_url or self.default_base_url):
            raise ProviderError("adresse du serveur manquante")

    def _base_url(self, cfg: ProviderConfig) -> str:
        return (cfg.base_url or self.default_base_url or "").rstrip("/")

    def _request(self, method: str, url: str, cfg: ProviderConfig, *, headers: dict[str, str],
                 json: Any = None, params: dict[str, Any] | None = None) -> Any:
        """Requête HTTP → JSON décodé, avec erreurs traduites en ProviderError."""
        timeout = httpx.Timeout(cfg.timeout_s, connect=min(10.0, cfg.timeout_s))
        kwargs = {"headers": headers, "json": json, "params": params, "timeout": timeout}
        try:
            if self._client is not None:
                response = self._client.request(method, url, **kwargs)
            else:
                with httpx.Client() as client:
                    response = client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"délai dépassé ({cfg.timeout_s:.0f} s)") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"connexion impossible ({exc.__class__.__name__})") from exc
        if response.status_code >= 400:
            raise ProviderError(_http_message(response.status_code, self._error_detail(response)),
                                response.status_code)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError("réponse non JSON du service") from exc

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        """Message d'erreur renvoyé par l'API (formats usuels), tronqué."""
        try:
            body = response.json()
        except ValueError:
            return response.text[:200].strip()
        if isinstance(body, list) and body:  # Gemini renvoie parfois une liste
            body = body[0]
        if not isinstance(body, dict):
            return ""
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("type") or "")[:300]
        if isinstance(err, str):
            return err[:300]
        return str(body.get("message") or "")[:300]

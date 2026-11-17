"""Appels Garmin encadrés : cadence, reprises sur 429, classement des résultats.

Chaque appel renvoie un :class:`FetchResult` au lieu de lever une exception, sauf
dans deux cas qui doivent interrompre la synchronisation :

* :class:`RateLimitAbort` : Garmin limite toujours après plusieurs attentes ;
* :class:`AuthRequiredError` : la session n'est plus valide et ne peut être restaurée.
"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from recoveriq.garmin.auth import AuthRequiredError, GarminAuth

log = logging.getLogger(__name__)

# garminconnect 0.3.2 encapsule le code HTTP dans le message (« API Error 404 - ... »).
_STATUS_RE = re.compile(r"(?:API Error|client error \(|error \()\s*(\d{3})", re.IGNORECASE)
# get_user_summary lève cette erreur lorsque Garmin renvoie une réponse vide.
_EMPTY_MESSAGES = ("No data received from server",)

RATE_LIMIT_WAITS_S = (60, 180, 600, 900)


class RateLimitAbort(Exception):
    """Garmin continue de répondre 429 : on interrompt, l'import reprendra plus tard."""


@dataclass
class FetchResult:
    outcome: str                      # ok | empty | unsupported | error
    payload: Any = None
    http_status: int | None = None
    error: str | None = None


def is_empty_payload(payload: Any) -> bool:
    return payload is None or payload == {} or payload == [] or payload == ""


def extract_status(exc: Exception) -> int | None:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status:
        return int(status)
    match = _STATUS_RE.search(str(exc))
    return int(match.group(1)) if match else None


class GarminClient:
    """Exécute les appels de la bibliothèque avec cadence et gestion d'erreurs."""

    def __init__(
        self,
        auth: GarminAuth,
        pause_s: float,
        jitter_s: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._auth = auth
        self._pause = pause_s
        self._jitter = jitter_s
        self._sleep = sleep
        self._last_call = 0.0
        self._lock = threading.Lock()
        self.calls = 0  # compteur pour le journal de synchro

    def _throttle(self) -> None:
        wait = self._last_call + self._pause + random.uniform(0, self._jitter) - time.monotonic()
        if wait > 0:
            self._sleep(wait)
        self._last_call = time.monotonic()

    def call(self, label: str, func: Callable[[Garmin], Any]) -> FetchResult:
        """Exécute ``func(garmin)`` et classe le résultat."""
        with self._lock:
            reauth_done = False
            rate_limit_attempt = 0
            while True:
                garmin = self._auth.client()  # lève AuthRequiredError si pas de session
                self._throttle()
                self.calls += 1
                try:
                    payload = func(garmin)
                except GarminConnectTooManyRequestsError as exc:
                    rate_limit_attempt = self._handle_rate_limit(label, exc, rate_limit_attempt)
                    continue
                except GarminConnectAuthenticationError as exc:
                    if reauth_done:
                        self._auth.invalidate("Session Garmin expirée : reconnectez-vous.")
                        raise AuthRequiredError(str(exc)) from exc
                    log.info("%s : session refusée, tentative de restauration", label)
                    reauth_done = True
                    self._auth.restore()
                    continue
                except GarminConnectConnectionError as exc:
                    status = extract_status(exc)
                    if status == 429:
                        rate_limit_attempt = self._handle_rate_limit(label, exc, rate_limit_attempt)
                        continue
                    if any(m in str(exc) for m in _EMPTY_MESSAGES):
                        return FetchResult("empty", http_status=204)
                    if status and 400 <= status < 500:
                        # 400/403/404 : endpoint non disponible pour ce compte / cette montre.
                        log.info("%s : non pris en charge (HTTP %s)", label, status)
                        return FetchResult("unsupported", http_status=status, error=str(exc)[:500])
                    log.warning("%s : erreur %s", label, exc)
                    return FetchResult("error", http_status=status, error=str(exc)[:500])
                except Exception as exc:  # bug de bibliothèque, réponse inattendue, réseau
                    log.warning("%s : erreur inattendue %r", label, exc)
                    return FetchResult("error", error=f"{type(exc).__name__}: {exc}"[:500])

                if is_empty_payload(payload):
                    return FetchResult("empty", payload=payload, http_status=200)
                return FetchResult("ok", payload=payload, http_status=200)

    def _handle_rate_limit(self, label: str, exc: Exception, attempt: int) -> int:
        if attempt >= len(RATE_LIMIT_WAITS_S):
            raise RateLimitAbort(f"Limitation Garmin persistante ({label}) : {exc}") from exc
        wait = RATE_LIMIT_WAITS_S[attempt]
        log.warning("%s : limitation Garmin (429), pause de %s s", label, wait)
        self._sleep(wait)
        return attempt + 1

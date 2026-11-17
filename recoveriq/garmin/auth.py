"""Authentification Garmin Connect (garminconnect >= 0.3, authentification native).

Cycle de vie :

1. Premier lancement : l'utilisateur saisit e-mail + mot de passe dans l'interface
   (:meth:`GarminAuth.start_login`). Si Garmin exige le MFA, l'état passe à
   ``mfa_required`` et l'instance Garmin est gardée en mémoire jusqu'à
   :meth:`GarminAuth.submit_mfa`.
2. En cas de succès : tokens sauvegardés (fichier chiffré DPAPI), mot de passe
   dans le Gestionnaire d'identifiants Windows, e-mail dans les paramètres.
3. Lancements suivants : :meth:`GarminAuth.restore` recharge les tokens. S'ils sont
   expirés et non rafraîchissables, reconnexion avec le mot de passe stocké ;
   si Garmin redemande le MFA, l'interface le demande à l'utilisateur.

Particularité de garminconnect 0.3.2 : avec ``return_on_mfa=True``, un login réussi
sans MFA retourne *avant* de charger le profil (``display_name`` vide, requis par
plusieurs endpoints). On finalise donc toujours par une seconde connexion à partir
des tokens, qui charge le profil complet.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectTooManyRequestsError,
)

from recoveriq import secrets_store
from recoveriq.db import repository as repo
from recoveriq.db.database import connect
from recoveriq.garmin.token_store import TokenStore

log = logging.getLogger(__name__)

# Garmin.login(tokenstore=...) interprète une chaîne de plus de 512 caractères comme
# des tokens sérialisés, et une chaîne plus courte comme un chemin de fichier.
# On complète donc par des espaces (ignorés par json.loads) pour forcer le premier cas.
_TOKENSTRING_MIN_LEN = 513

SETTING_EMAIL = "garmin.email"
SETTING_DISPLAY_NAME = "garmin.display_name"


@dataclass
class AuthStatus:
    state: str                    # not_configured | connecting | connected | mfa_required | error
    email: str | None = None
    display_name: str | None = None
    message: str | None = None


class AuthRequiredError(Exception):
    """Aucune session Garmin valide : une action de l'utilisateur est nécessaire."""


class GarminAuth:
    def __init__(self, token_store: TokenStore, garmin_factory: Callable[..., Garmin] = Garmin) -> None:
        self._tokens = token_store
        self._factory = garmin_factory
        self._lock = threading.RLock()
        self._garmin: Garmin | None = None
        self._pending_mfa: Garmin | None = None
        self._pending_email: str | None = None
        self._pending_password: str | None = None
        self._status = AuthStatus(state="not_configured")
        self._on_connected: list[Callable[[str], None]] = []

    # --- État ---------------------------------------------------------------

    def status(self) -> AuthStatus:
        with self._lock:
            return AuthStatus(**vars(self._status))

    def on_connected(self, callback: Callable[[str], None]) -> None:
        """Enregistre un rappel déclenché après une connexion réussie (argument : origine)."""
        self._on_connected.append(callback)

    def client(self) -> Garmin:
        """Renvoie le client connecté, ou lève :class:`AuthRequiredError`."""
        with self._lock:
            if self._garmin is None:
                raise AuthRequiredError(self._status.message or "Connexion Garmin requise")
            return self._garmin

    # --- Connexion interactive ------------------------------------------------

    def start_login(self, email: str, password: str) -> AuthStatus:
        """Première connexion (ou changement de compte) depuis l'interface."""
        email = email.strip()
        with self._lock:
            self._set(AuthStatus("connecting", email=email))
            try:
                garmin = self._factory(email, password, return_on_mfa=True)
                mfa_status, _ = garmin.login()
            except GarminConnectTooManyRequestsError:
                return self._fail(email, "Trop de tentatives : Garmin bloque temporairement. Réessayez dans quelques minutes.")
            except GarminConnectAuthenticationError:
                return self._fail(email, "Identifiants refusés par Garmin.")
            except Exception as exc:  # réseau, Cloudflare, changement d'API...
                log.exception("Échec de connexion Garmin")
                return self._fail(email, f"Connexion impossible : {exc}")

            if mfa_status == "needs_mfa":
                self._pending_mfa, self._pending_email, self._pending_password = garmin, email, password
                return self._set(AuthStatus("mfa_required", email=email,
                                            message="Saisissez le code reçu par e-mail ou SMS."))
            return self._finalize(garmin, email, password, origin="login")

    def submit_mfa(self, code: str) -> AuthStatus:
        with self._lock:
            if self._pending_mfa is None or self._pending_email is None:
                return self._set(AuthStatus("error", message="Aucune connexion en attente de code MFA."))
            garmin, email, password = self._pending_mfa, self._pending_email, self._pending_password
            try:
                garmin.resume_login({}, code.strip())  # l'état MFA est porté par l'instance
            except Exception as exc:
                log.warning("Code MFA refusé : %s", exc)
                return self._set(AuthStatus("mfa_required", email=email,
                                            message="Code refusé ou expiré. Réessayez."))
            self._pending_mfa = self._pending_email = self._pending_password = None
            return self._finalize(garmin, email, password or "", origin="login")

    # --- Restauration automatique --------------------------------------------

    def restore(self) -> AuthStatus:
        """Restaure la session au démarrage ou après expiration. Ne lève pas d'exception."""
        with self._lock:
            with connect() as conn:
                email = repo.get_setting(conn, SETTING_EMAIL)
            if not email:
                return self._set(AuthStatus("not_configured", message="Connexion Garmin à configurer."))

            self._set(AuthStatus("connecting", email=email))
            tokens = self._tokens.load()
            if tokens:
                try:
                    garmin = self._factory()
                    garmin.login(tokenstore=tokens.ljust(_TOKENSTRING_MIN_LEN))
                    return self._connected(garmin, email, origin="restore")
                except Exception as exc:
                    log.info("Tokens Garmin inutilisables (%s), reconnexion par mot de passe", exc)

            password = secrets_store.get_garmin_password(email)
            if not password:
                return self._fail(email, "Mot de passe absent du Gestionnaire d'identifiants : reconnectez-vous.")
            return self.start_login(email, password)

    def persist_tokens(self) -> None:
        """Sauvegarde les tokens courants (ils peuvent avoir été rafraîchis pendant une synchro)."""
        with self._lock:
            if self._garmin is not None:
                try:
                    self._tokens.save(self._garmin.client.dumps())
                except Exception:
                    log.exception("Sauvegarde des tokens impossible")

    def invalidate(self, reason: str) -> None:
        """Appelé par le client quand Garmin renvoie une erreur d'authentification."""
        with self._lock:
            self._garmin = None
            self._set(AuthStatus("error", email=self._status.email, message=reason))

    def logout(self) -> AuthStatus:
        with self._lock:
            with connect() as conn:
                email = repo.get_setting(conn, SETTING_EMAIL)
                repo.delete_setting(conn, SETTING_EMAIL)
                repo.delete_setting(conn, SETTING_DISPLAY_NAME)
            if email:
                secrets_store.delete_garmin_password(email)
            self._tokens.delete()
            self._garmin = self._pending_mfa = None
            return self._set(AuthStatus("not_configured", message="Déconnecté."))

    # --- Interne --------------------------------------------------------------

    def _finalize(self, garmin: Garmin, email: str, password: str, origin: str) -> AuthStatus:
        """Sauvegarde tokens + secrets, puis ouvre une session complète depuis les tokens."""
        try:
            tokens = garmin.client.dumps()
            self._tokens.save(tokens)
            full = self._factory()
            full.login(tokenstore=tokens.ljust(_TOKENSTRING_MIN_LEN))
        except Exception as exc:
            log.exception("Finalisation de la connexion Garmin impossible")
            return self._fail(email, f"Connexion établie mais profil inaccessible : {exc}")
        if password:
            secrets_store.set_garmin_password(email, password)
        return self._connected(full, email, origin)

    def _connected(self, garmin: Garmin, email: str, origin: str) -> AuthStatus:
        self._garmin = garmin
        display = getattr(garmin, "display_name", None)
        with connect() as conn:
            repo.set_setting(conn, SETTING_EMAIL, email)
            repo.set_setting(conn, SETTING_DISPLAY_NAME, display)
        self.persist_tokens()
        status = self._set(AuthStatus("connected", email=email, display_name=display))
        log.info("Session Garmin ouverte (%s)", origin)
        for callback in self._on_connected:
            try:
                callback(origin)
            except Exception:
                log.exception("Rappel post-connexion en échec")
        return status

    def _fail(self, email: str | None, message: str) -> AuthStatus:
        self._garmin = None
        return self._set(AuthStatus("error", email=email, message=message))

    def _set(self, status: AuthStatus) -> AuthStatus:
        self._status = status
        return AuthStatus(**vars(status))

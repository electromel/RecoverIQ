"""Point d'entrée : application FastAPI.

Lancement : ``python -m recoveriq`` (voir README).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import resources

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from recoveriq.ai import settings as ai_settings
from recoveriq.ai import store as ai_store
from recoveriq.ai.service import AnalysisService
from recoveriq.api import routes_ai, routes_auth, routes_dashboard, routes_sync
from recoveriq.api.deps import Services
from recoveriq.config import Settings, is_packaged_process, legacy_home, settings
from recoveriq.db import repository as repo
from recoveriq.db.database import connect, init_db
from recoveriq.db.legacy_migration import migrate_legacy_home
from recoveriq.garmin.auth import GarminAuth
from recoveriq.garmin.sync import SyncService, backfill_needed
from recoveriq.garmin.token_store import TokenStore
from recoveriq.logging_setup import setup_logging
from recoveriq.scheduler import build_scheduler, needs_catch_up, schedule_weekly_report

log = logging.getLogger(__name__)

STATIC_DIR = resources.files("recoveriq") / "static"


def _on_connected(sync: SyncService, origin: str) -> None:
    """Après connexion : import historique s'il reste à faire, sinon rattrapage éventuel."""
    if origin == "login" or needs_catch_up():
        sync.request_incremental(origin)
    if backfill_needed():
        sync.request_backfill(origin)


def create_app(cfg: Settings = settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        setup_logging(cfg)
        cfg.ensure_dirs()
        if is_packaged_process():
            # Dans un paquet MSIX, la lecture d'AppData peut renvoyer une copie redirigée
            # (obsolète) au lieu des vraies données : la migration est reportée.
            log.warning("Processus empaqueté (MSIX) : migration depuis %s reportée", legacy_home())
        else:
            migrate_legacy_home(legacy_home(), cfg.home)
        init_db(cfg.db_path)
        with connect() as conn:
            repo.mark_stale_runs_interrupted(conn)
            ai_store.mark_stale_running(conn)
            weekly = ai_settings.load(conn)["weekly"]

        auth = GarminAuth(TokenStore(cfg.token_path))
        sync = SyncService(auth, cfg)
        auth.on_connected(lambda origin: _on_connected(sync, origin))
        ai = AnalysisService()

        sync.start()
        scheduler = build_scheduler(cfg, sync)
        schedule_weekly_report(scheduler, ai, weekly)
        scheduler.start()
        app.state.services = Services(auth=auth, sync=sync, ai=ai, scheduler=scheduler)
        # Restauration de session en arrière-plan : le serveur répond immédiatement.
        threading.Thread(target=auth.restore, name="recoveriq-auth-restore", daemon=True).start()
        log.info("RecoverIQ démarré sur http://%s:%s (données : %s)", cfg.host, cfg.port, cfg.home)
        try:
            yield
        finally:
            scheduler.shutdown(wait=False)
            sync.stop()
            log.info("RecoverIQ arrêté")

    app = FastAPI(title="RecoverIQ", version="0.3.0", lifespan=lifespan)
    app.include_router(routes_auth.router)
    app.include_router(routes_sync.router)
    app.include_router(routes_dashboard.router)
    app.include_router(routes_ai.router)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.middleware("http")
    async def no_stale_assets(request: Request, call_next):  # type: ignore[no-untyped-def]
        # Revalidation systématique (ETag) : une mise à jour de l'appli est visible sans vider le cache.
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> RedirectResponse:
        # Requête implicite des navigateurs : renvoyée vers l'icône SVG.
        return RedirectResponse("/static/img/icon.svg", status_code=301)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(str(STATIC_DIR / "index.html"))

    return app


app = create_app()

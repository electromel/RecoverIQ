"""Moteur de synchronisation.

Deux types de travaux, exécutés un par un dans un thread dédié :

* **incrémental** (quotidien, bouton « Synchroniser maintenant », démarrage) :
  resynchronise toujours les ``resync_days`` derniers jours, plus tout jour manqué
  depuis la dernière synchro réussie ;
* **import historique** (backfill) : remonte du plus récent au plus ancien, par
  blocs de 30 jours alignés sur le calendrier, avec reprise via ``import_progress``.
  Un incrémental demandé pendant l'import est exécuté entre deux jours, sans
  attendre la fin (plusieurs heures).

Chaque appel conserve la réponse brute, puis alimente les tables normalisées.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from recoveriq.config import Settings
from recoveriq.db import repository as repo
from recoveriq.db.database import connect
from recoveriq.garmin.auth import AuthRequiredError, GarminAuth
from recoveriq.garmin.client import FetchResult, GarminClient, RateLimitAbort
from recoveriq.garmin.registry import (
    DAILY_FETCHERS,
    RANGE_FETCHERS,
    Fetcher,
    Scope,
    find_earliest_activity_date,
)

log = logging.getLogger(__name__)

# Ancre fixe des blocs de l'import historique : les bornes ne dépendent pas du
# jour de lancement, ce qui garantit une reprise exacte d'un jour à l'autre.
_BLOCK_ANCHOR = date(2000, 1, 1)
_DEFAULT_HISTORY_YEARS = 3

SETTING_BACKFILL_START = "backfill.start_date"
SETTING_BACKFILL_COMPLETE = "backfill.complete"
SETTING_BACKFILL_STOPPED = "backfill.stopped_fetchers"
SETTING_BACKFILL_FETCHERS = "backfill.fetchers"   # appels couverts par le dernier import complet
SETTING_LAST_SYNCED = "sync.last_synced_date"


class SyncStopped(Exception):
    """Arrêt de l'application demandé pendant une synchronisation."""


@dataclass
class RunStats:
    run_id: int
    days: int = 0
    errors: int = 0
    current: str | None = None


@dataclass
class _Job:
    kind: str       # 'incremental' | 'backfill'
    trigger: str


@dataclass
class _Live:
    """État courant exposé à l'interface."""
    kind: str | None = None
    trigger: str | None = None
    current: str | None = None
    days_done: int = 0
    errors: int = 0
    queued: list[str] = field(default_factory=list)


class SyncService:
    def __init__(
        self,
        auth: GarminAuth,
        cfg: Settings,
        today: Callable[[], date] = date.today,
        client: GarminClient | None = None,
    ) -> None:
        self._auth = auth
        self._cfg = cfg
        self._today = today
        self._stop = threading.Event()
        self._preempt = threading.Event()   # incrémental demandé pendant un backfill
        self._jobs: queue.Queue[_Job | None] = queue.Queue()
        self._live = _Live()
        self._live_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.client = client or GarminClient(
            auth, cfg.request_pause_s, cfg.request_jitter_s, sleep=self._interruptible_sleep
        )

    # ------------------------------------------------------------------
    # Cycle de vie et commandes
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._worker, name="recoveriq-sync", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10) -> None:
        self._stop.set()
        self._jobs.put(None)
        if self._thread:
            self._thread.join(timeout)

    def request_incremental(self, trigger: str) -> str:
        with self._live_lock:
            if self._live.kind == "backfill":
                self._preempt.set()
                return "Synchronisation insérée dans l'import historique en cours."
            if self._live.kind == "incremental" or "incremental" in self._live.queued:
                return "Une synchronisation est déjà en cours ou en attente."
            self._live.queued.append("incremental")
        self._jobs.put(_Job("incremental", trigger))
        return "Synchronisation lancée."

    def request_backfill(self, trigger: str) -> str:
        with self._live_lock:
            if self._live.kind == "backfill" or "backfill" in self._live.queued:
                return "L'import historique est déjà en cours ou en attente."
            self._live.queued.append("backfill")
        self._jobs.put(_Job("backfill", trigger))
        return "Import historique lancé."

    def status(self) -> dict[str, Any]:
        with self._live_lock:
            live = {
                "running": self._live.kind is not None,
                "kind": self._live.kind,
                "trigger": self._live.trigger,
                "current": self._live.current,
                "days_done": self._live.days_done,
                "errors": self._live.errors,
                "queued": list(self._live.queued),
            }
        with connect() as conn:
            start = repo.get_setting(conn, SETTING_BACKFILL_START)
            complete = bool(repo.get_setting(conn, SETTING_BACKFILL_COMPLETE, False))
            last_synced = repo.get_setting(conn, SETTING_LAST_SYNCED)
            done_days = conn.execute(
                "SELECT COUNT(*) FROM import_progress WHERE fetcher = ? AND status IN ('done', 'skipped')",
                (DAILY_FETCHERS[0].name,),
            ).fetchone()[0]
            progress = repo.progress_summary(conn)
        total_days = (self._today() - date.fromisoformat(start)).days + 1 if start else None
        live["backfill"] = {
            "start_date": start,
            "complete": complete,
            "days_done": done_days,
            "days_total": total_days,
            "pending_errors": progress.get("error", 0),
        }
        live["last_synced_date"] = last_synced
        return live

    # ------------------------------------------------------------------
    # Boucle du thread de synchronisation
    # ------------------------------------------------------------------

    def _worker(self) -> None:
        while not self._stop.is_set():
            job = self._jobs.get()
            if job is None:
                break
            with self._live_lock:
                if job.kind in self._live.queued:
                    self._live.queued.remove(job.kind)
                self._live = _Live(kind=job.kind, trigger=job.trigger, queued=self._live.queued)
            try:
                self._run(job)
            except Exception:
                log.exception("Erreur inattendue dans le thread de synchronisation")
            finally:
                with self._live_lock:
                    self._live = _Live(queued=self._live.queued)

    def _run(self, job: _Job) -> None:
        with connect() as conn:
            run_id = repo.start_run(conn, job.kind, job.trigger)
        stats = RunStats(run_id)
        calls_before = self.client.calls
        status, message = "success", None
        try:
            self._auth.client()  # vérifie la session avant tout
            if job.kind == "backfill":
                message = self._backfill(stats)
            else:
                self._incremental(stats)
            if stats.errors:
                status = "partial"
        except AuthRequiredError as exc:
            status, message = "failed", f"Garmin non connecté : {exc}"
        except RateLimitAbort as exc:
            status, message = "interrupted", f"{exc}. Reprise automatique au prochain passage."
        except SyncStopped:
            status, message = "interrupted", "Arrêt de l'application."
        except Exception as exc:
            log.exception("Synchronisation %s en échec", job.kind)
            status, message = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            self._auth.persist_tokens()
            with connect() as conn:
                repo.finish_run(conn, run_id, status, stats.days,
                                self.client.calls - calls_before, stats.errors, message)
            log.info("Synchro %s terminée : %s (%s jours, %s erreurs)",
                     job.kind, status, stats.days, stats.errors)

    # ------------------------------------------------------------------
    # Synchronisation incrémentale
    # ------------------------------------------------------------------

    def _incremental(self, stats: RunStats) -> None:
        today = self._today()
        start = today - timedelta(days=self._cfg.resync_days)
        with connect() as conn:
            last = repo.get_setting(conn, SETTING_LAST_SYNCED)
            backfill_start = repo.get_setting(conn, SETTING_BACKFILL_START)
        if last:
            start = min(start, date.fromisoformat(last))  # rattrape les jours manqués
        if backfill_start:
            start = max(start, date.fromisoformat(backfill_start))

        day = today
        while day >= start:
            self._check_stop()
            iso = day.isoformat()
            for fetcher in DAILY_FETCHERS:
                self._fetch(fetcher, iso, iso, stats, track_progress=True)
            for fetcher in RANGE_FETCHERS:
                if fetcher.incremental_daily:
                    self._fetch(fetcher.incremental_daily, iso, iso, stats, track_progress=False)
            stats.days += 1
            self._set_live(days_done=stats.days)
            day -= timedelta(days=1)

        for fetcher in RANGE_FETCHERS:
            if fetcher.incremental_daily:
                continue
            for chunk_start, chunk_end in _chunks(start, today, self._cfg.range_chunk_days):
                self._fetch(fetcher, chunk_start.isoformat(), chunk_end.isoformat(), stats,
                            track_progress=False)

        with connect() as conn:
            repo.set_setting(conn, SETTING_LAST_SYNCED, today.isoformat())

    # ------------------------------------------------------------------
    # Import historique avec reprise
    # ------------------------------------------------------------------

    def _backfill(self, stats: RunStats) -> str:
        start = self._resolve_history_start()
        today = self._today()
        with connect() as conn:
            progress = {f.name: repo.get_progress(conn, f.name) for f in DAILY_FETCHERS + RANGE_FETCHERS}
            stopped: dict[str, str] = repo.get_setting(conn, SETTING_BACKFILL_STOPPED, {}) or {}
        streaks = {f.name: 0 for f in DAILY_FETCHERS}

        for block_start, block_end in _aligned_blocks(start, today, self._cfg.range_chunk_days):
            # 1) Appels par plage : peu nombreux, ils rendent vite l'historique des activités visible.
            for fetcher in RANGE_FETCHERS:
                key = block_start.isoformat()
                if self._should_skip(progress[fetcher.name].get(key)):
                    continue
                self._fetch(fetcher, key, block_end.isoformat(), stats, track_progress=True)

            # 2) Appels journaliers, du plus récent au plus ancien.
            day = block_end
            while day >= block_start:
                self._check_stop()
                if self._preempt.is_set():
                    self._preempt.clear()
                    log.info("Synchro incrémentale insérée dans l'import historique")
                    self._incremental(stats)
                iso = day.isoformat()
                for fetcher in DAILY_FETCHERS:
                    if fetcher.name in stopped or self._should_skip(progress[fetcher.name].get(iso)):
                        continue
                    has_data = self._fetch(fetcher, iso, iso, stats, track_progress=True)
                    streaks[fetcher.name] = 0 if has_data else streaks[fetcher.name] + 1
                    if streaks[fetcher.name] >= self._cfg.empty_streak_stop_days:
                        stopped[fetcher.name] = iso
                        with connect() as conn:
                            repo.set_setting(conn, SETTING_BACKFILL_STOPPED, stopped)
                        log.info("%s : aucune donnée depuis %s jours, arrêt de l'import avant %s",
                                 fetcher.name, self._cfg.empty_streak_stop_days, iso)
                stats.days += 1
                self._set_live(days_done=stats.days)
                day -= timedelta(days=1)

        with connect() as conn:
            repo.set_setting(conn, SETTING_BACKFILL_COMPLETE, True)
            repo.set_setting(conn, SETTING_BACKFILL_FETCHERS, sorted(f.name for f in DAILY_FETCHERS + RANGE_FETCHERS))
            pending = repo.progress_summary(conn).get("error", 0)
        msg = f"Import historique terminé depuis le {start.isoformat()}."
        if stopped:
            msg += " Arrêt anticipé (aucune donnée plus ancienne) : " + ", ".join(
                f"{name} avant {d}" for name, d in sorted(stopped.items()))
        if pending:
            msg += f" {pending} appel(s) en erreur seront retentés au prochain import."
        return msg

    def _should_skip(self, progress_row: Any) -> bool:
        if progress_row is None:
            return False
        if progress_row["status"] in ("done", "skipped"):
            return True
        return progress_row["attempts"] >= self._cfg.max_attempts

    def _resolve_history_start(self) -> date:
        with connect() as conn:
            stored = repo.get_setting(conn, SETTING_BACKFILL_START)
        if stored:
            return date.fromisoformat(stored)
        if self._cfg.history_start:
            start = date.fromisoformat(self._cfg.history_start)
        else:
            self._set_live(current="Recherche de la première activité")
            result = self.client.call("première activité", find_earliest_activity_date)
            if result.outcome == "ok" and result.payload:
                start = date.fromisoformat(result.payload)
            else:
                start = self._today() - timedelta(days=365 * _DEFAULT_HISTORY_YEARS)
                log.info("Première activité introuvable, historique limité à %s ans", _DEFAULT_HISTORY_YEARS)
        with connect() as conn:
            repo.set_setting(conn, SETTING_BACKFILL_START, start.isoformat())
        return start

    # ------------------------------------------------------------------
    # Un appel : brut + normalisé + disponibilité + avancement
    # ------------------------------------------------------------------

    def _fetch(self, fetcher: Fetcher, start: str, end: str, stats: RunStats, track_progress: bool) -> bool:
        """Exécute un fetcher et renvoie True si au moins une valeur a été obtenue."""
        label = f"{fetcher.label} · {start}" + (f" → {end}" if end != start else "")
        self._set_live(current=label)
        if fetcher.scope is Scope.DAILY:
            result: FetchResult = self.client.call(label, lambda g: fetcher.call(g, start))
        else:
            result = self.client.call(label, lambda g: fetcher.call(g, start, end))

        has_data = False
        error = result.error if result.outcome == "error" else None
        with connect() as conn:
            repo.save_raw(conn, fetcher.name, start, end, result.outcome, result.payload,
                          result.http_status, result.error)
            if result.outcome != "error":
                try:
                    payload = result.payload if result.outcome == "ok" else {}
                    rows = fetcher.parser(payload, start) if fetcher.scope is Scope.DAILY \
                        else fetcher.parser(payload, start, end)
                    for table, table_rows in rows.items():
                        if table_rows:
                            repo.upsert_rows(conn, table, table_rows)
                            has_data = True
                        repo.touch_availability(conn, table, [r["date"] for r in table_rows])
                except Exception as exc:  # parser à corriger ; le brut est conservé
                    log.exception("Parser %s en échec pour %s", fetcher.name, start)
                    error = f"Erreur d'analyse : {type(exc).__name__}: {exc}"
                if fetcher.has_detail and result.outcome == "ok":
                    has_data = fetcher.has_detail(result.payload)
            if track_progress:
                repo.mark_progress(conn, fetcher.name, start, end, "error" if error else "done", error)
            if error:
                repo.add_run_error(conn, stats.run_id, fetcher.name, start, error)
        if error:
            stats.errors += 1
            self._set_live(errors=stats.errors)
        return has_data

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------

    def _set_live(self, **values: Any) -> None:
        with self._live_lock:
            for key, value in values.items():
                setattr(self._live, key, value)

    def _check_stop(self) -> None:
        if self._stop.is_set():
            raise SyncStopped()

    def _interruptible_sleep(self, seconds: float) -> None:
        if self._stop.wait(seconds):
            raise SyncStopped()


def backfill_needed() -> bool:
    """Import historique à (re)lancer : jamais terminé, ou un appel ajouté depuis.

    Les appels déjà importés sont sautés (``import_progress``) : seule la nouvelle
    série est remontée, jusqu'à ``empty_streak_stop_days`` jours vides consécutifs.
    """
    with connect() as conn:
        complete = repo.get_setting(conn, SETTING_BACKFILL_COMPLETE, False)
        covered = repo.get_setting(conn, SETTING_BACKFILL_FETCHERS)
    if not complete or covered is None:
        return True
    return bool({f.name for f in DAILY_FETCHERS + RANGE_FETCHERS} - set(covered))


def _chunks(start: date, end: date, size: int) -> list[tuple[date, date]]:
    """Découpe [start, end] en morceaux de ``size`` jours au plus."""
    out, cur = [], start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=size - 1), end)
        out.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return out


def _aligned_blocks(start: date, end: date, size: int) -> list[tuple[date, date]]:
    """Blocs alignés sur une ancre fixe, du plus récent au plus ancien, bornés à [start, end].

    Le bloc contenant ``end`` (aujourd'hui) est tronqué à aujourd'hui ; les jours
    suivants sont couverts par la synchronisation incrémentale. Grâce à l'ancre fixe,
    la clé de reprise d'un bloc (sa date de début) est identique d'un lancement à l'autre.
    """
    blocks = []
    idx = (end - _BLOCK_ANCHOR).days // size
    while True:
        b_start = _BLOCK_ANCHOR + timedelta(days=idx * size)
        b_end = b_start + timedelta(days=size - 1)
        if b_end < start:
            break
        blocks.append((max(b_start, start), min(b_end, end)))
        idx -= 1
    return blocks

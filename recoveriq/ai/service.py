"""Orchestration d'une analyse : résumé → fournisseurs en parallèle → agrégation → archivage.

* Une seule analyse à la fois (verrou) ; elle s'exécute dans un fil d'arrière-plan et
  l'interface suit son avancement via :meth:`AnalysisService.status`.
* Chaque fournisseur actif est appelé en parallèle avec un délai maximal. Un échec
  (clé refusée, délai dépassé, JSON inexploitable…) est consigné et n'empêche pas les
  autres de répondre.
* Agrégation :
    - 1 rapport valide → affiché tel quel (mode ``single``) ;
    - plusieurs → comparaison déterministe (toujours) + synthèse par l'agrégateur
      désigné (mode ``llm``) ; si elle échoue, repli sur la comparaison (``fallback``).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta, timezone
from typing import Any

from recoveriq.ai import settings as ai_settings
from recoveriq.ai import store
from recoveriq.ai.compare import compare_reports
from recoveriq.ai.prompts import ANALYSIS_SYSTEM, SYNTHESIS_SYSTEM, analysis_user_prompt, synthesis_user_prompt
from recoveriq.ai.providers import LLMProvider, ProviderError, ProviderTimeout, build_registry
from recoveriq.ai.report_format import ReportFormatError, extract_json, parse_report, validate_synthesis
from recoveriq.ai.summary import build_summary
from recoveriq.db.database import connect

log = logging.getLogger(__name__)

RAW_TEXT_LIMIT = 20_000
# Marge au-delà du délai HTTP avant d'abandonner un fournisseur (lecture lente en continu…).
WAIT_MARGIN_S = 15


class AnalysisBusy(RuntimeError):
    pass


class NoProviderEnabled(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AnalysisService:
    def __init__(self, registry: dict[str, LLMProvider] | None = None,
                 today: Callable[[], date] = date.today) -> None:
        self.registry = registry or build_registry()
        self._today = today
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"running": False}
        self._thread: threading.Thread | None = None

    # --- Interface publique ----------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {**self._state, "providers": dict(self._state.get("providers", {}))}

    def start(self, period_days: int, trigger: str = "manual", end: date | None = None) -> int:
        """Lance une analyse en arrière-plan ; renvoie l'identifiant du rapport."""
        with connect() as conn:
            settings = ai_settings.load(conn)
        enabled = [pid for pid in self.registry if settings["providers"][pid]["enabled"]]
        if not enabled:
            raise NoProviderEnabled("Aucun fournisseur d'IA n'est activé (page Fournisseurs IA).")
        end = end or self._today()
        start = end - timedelta(days=period_days - 1)
        with self._lock:
            if self._state.get("running"):
                raise AnalysisBusy("Une analyse est déjà en cours.")
            with connect() as conn:
                report_id = store.create_report(conn, trigger, start.isoformat(), end.isoformat(), period_days)
            self._state = {"running": True, "report_id": report_id, "started_at": _now(), "trigger": trigger,
                           "period_days": period_days, "step": "summary",
                           "providers": {pid: "pending" for pid in enabled}}
        self._thread = threading.Thread(target=self._run_safe, args=(report_id, settings, enabled, end, period_days),
                                        name="recoveriq-ai", daemon=True)
        self._thread.start()
        return report_id

    def run_blocking(self, period_days: int, trigger: str = "manual", end: date | None = None) -> int:
        """Variante synchrone (tests, planificateur)."""
        report_id = self.start(period_days, trigger, end)
        if self._thread:
            self._thread.join()
        return report_id

    def run_scheduled(self, period_days: int) -> None:
        """Tâche hebdomadaire : silencieuse si rien n'est configuré ou si une analyse tourne."""
        try:
            self.run_blocking(period_days, "scheduler")
        except (NoProviderEnabled, AnalysisBusy) as exc:
            log.info("Rapport hebdomadaire non lancé : %s", exc)

    # --- Déroulement ------------------------------------------------------------

    def _set(self, **changes: Any) -> None:
        with self._lock:
            self._state.update(changes)

    def _set_provider(self, pid: str, state: str) -> None:
        with self._lock:
            self._state.setdefault("providers", {})[pid] = state

    def _run_safe(self, report_id: int, settings: dict[str, Any], enabled: list[str], end: date,
                  days: int) -> None:
        try:
            self._run(report_id, settings, enabled, end, days)
        except Exception as exc:  # garde-fou : le rapport ne reste jamais « en cours »
            log.exception("Analyse IA %s en échec", report_id)
            with connect() as conn:
                store.finish_report(conn, report_id, status="failed", error=str(exc)[:500])
        finally:
            self._set(running=False, step="done")

    def _run(self, report_id: int, settings: dict[str, Any], enabled: list[str], end: date, days: int) -> None:
        with connect() as conn:
            summary = build_summary(conn, end, days)
            store.save_summary(conn, report_id, summary)
        if not summary["metrics"]:
            with connect() as conn:
                store.finish_report(conn, report_id, status="failed",
                                    error="Aucune donnée sur la période : rien à analyser.")
            return

        self._set(step="providers")
        user_prompt = analysis_user_prompt(summary)
        results = self._call_all(settings, enabled, user_prompt)
        with connect() as conn:
            for r in results.values():
                store.save_result(conn, report_id, r)

        valid = {pid: r["report"] for pid, r in results.items() if r["status"] == "ok"}
        # Coût : appels ayant abouti (facturés), y compris les réponses au format invalide.
        costs = [r.get("cost") for r in results.values() if r["status"] in ("ok", "invalid")]

        fields: dict[str, Any] = {}
        if not valid:
            fields.update(status="failed", error="Aucun fournisseur n'a rendu de rapport exploitable.")
        else:
            fields["status"] = "success" if len(valid) == len(results) else "partial"
            fields["comparison"] = compare_reports(valid) if len(valid) > 1 else None
            if len(valid) == 1:
                fields["synthesis_mode"] = "single"
            else:
                self._set(step="synthesis")
                fields.update(self._synthesize(settings, valid))
                if fields["synthesis_mode"] == "llm":
                    costs.append(fields.get("aggregator_cost"))
        known = [c for c in costs if c is not None]
        fields.update(total_cost=round(sum(known), 6) if known else None,
                      cost_complete=int(bool(costs) and len(known) == len(costs)))
        with connect() as conn:
            store.finish_report(conn, report_id, **fields)

    def _call_one(self, pid: str, settings: dict[str, Any], user_prompt: str) -> dict[str, Any]:
        provider = self.registry[pid]
        cfg = ai_settings.provider_config(settings, pid)
        out: dict[str, Any] = {"provider": pid, "model": cfg.model, "status": "error"}
        self._set_provider(pid, "running")
        try:
            completion = provider.complete(cfg, ANALYSIS_SYSTEM, user_prompt)
        except ProviderTimeout as exc:
            out.update(status="timeout", error=str(exc))
        except ProviderError as exc:
            out.update(error=str(exc))
        except Exception as exc:  # erreur inattendue d'un adaptateur : isolée
            log.exception("Fournisseur %s", pid)
            out.update(error=f"erreur inattendue ({exc.__class__.__name__})")
        else:
            out.update(model=completion.model, duration_ms=completion.duration_ms,
                       input_tokens=completion.input_tokens, output_tokens=completion.output_tokens,
                       raw_text=completion.text[:RAW_TEXT_LIMIT],
                       cost=ai_settings.estimate_cost(settings, pid, completion.input_tokens,
                                                      completion.output_tokens))
            try:
                out["report"], out["warnings"] = parse_report(completion.text)
                out["status"] = "ok"
            except ReportFormatError as exc:
                out.update(status="invalid", error=f"format de réponse non respecté : {exc}")
        self._set_provider(pid, out["status"])
        return out

    def _call_all(self, settings: dict[str, Any], enabled: list[str], user_prompt: str) -> dict[str, dict[str, Any]]:
        timeout = float(settings["timeout_s"]) + WAIT_MARGIN_S
        pool = ThreadPoolExecutor(max_workers=len(enabled), thread_name_prefix="recoveriq-llm")
        futures = {pid: pool.submit(self._call_one, pid, settings, user_prompt) for pid in enabled}
        wait(futures.values(), timeout=timeout)
        results: dict[str, dict[str, Any]] = {}
        for pid, fut in futures.items():
            if fut.done():
                results[pid] = fut.result()
            else:
                cfg = settings["providers"][pid]
                results[pid] = {"provider": pid, "model": cfg.get("model"), "status": "timeout",
                                "error": f"délai dépassé ({timeout:.0f} s)"}
                self._set_provider(pid, "timeout")
        pool.shutdown(wait=False, cancel_futures=True)
        return results

    def _synthesize(self, settings: dict[str, Any], valid: dict[str, dict[str, Any]]) -> dict[str, Any]:
        choice = settings.get("aggregator") or ai_settings.AGGREGATOR_NONE
        if choice == ai_settings.AGGREGATOR_NONE:
            return {"synthesis_mode": "fallback"}
        pid = next(iter(valid)) if choice == ai_settings.AGGREGATOR_AUTO else choice
        out: dict[str, Any] = {"aggregator": pid, "synthesis_mode": "fallback"}
        if pid not in self.registry:
            out["aggregator_error"] = "agrégateur inconnu"
            return out
        cfg = ai_settings.provider_config(settings, pid)
        out["aggregator_model"] = cfg.model
        labels = {p: f"{self.registry[p].label} — {settings['providers'][p]['model']}" for p in valid}
        try:
            completion = self.registry[pid].complete(cfg, SYNTHESIS_SYSTEM, synthesis_user_prompt(valid, labels))
            out["aggregator_cost"] = ai_settings.estimate_cost(settings, pid, completion.input_tokens,
                                                               completion.output_tokens)
            out["synthesis"] = validate_synthesis(extract_json(completion.text))
            out["synthesis_mode"] = "llm"
        except (ProviderError, ReportFormatError) as exc:
            out["aggregator_error"] = str(exc)
        except Exception as exc:
            log.exception("Agrégateur %s", pid)
            out["aggregator_error"] = f"erreur inattendue ({exc.__class__.__name__})"
        return out

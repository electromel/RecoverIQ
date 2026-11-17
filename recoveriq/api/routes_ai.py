"""Analyse IA : fournisseurs (réglages, clés, test), lancement, suivi et archives des rapports."""

from __future__ import annotations

import webbrowser
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from recoveriq.ai import settings as ai_settings
from recoveriq.ai import store
from recoveriq.ai.prompts import DISCLAIMER
from recoveriq.ai.report_format import METRIC_LABELS
from recoveriq.ai.service import AnalysisBusy, NoProviderEnabled
from recoveriq.ai.summary import build_summary
from recoveriq.api.deps import Services, get_services
from recoveriq.db.database import connect
from recoveriq.scheduler import schedule_weekly_report

router = APIRouter(prefix="/api/ai", tags=["ai"])


class ProviderUpdate(BaseModel):
    enabled: bool | None = None
    model: str | None = Field(None, max_length=200)
    base_url: str | None = Field(None, max_length=500)
    price_in: float | None = Field(None, ge=0)
    price_out: float | None = Field(None, ge=0)
    clear_prices: bool = False
    api_key: str | None = Field(None, max_length=500)   # écrite dans le trousseau, jamais renvoyée
    delete_key: bool = False


class TestRequest(BaseModel):
    # Valeurs saisies mais pas encore enregistrées (facultatives).
    model: str | None = Field(None, max_length=200)
    base_url: str | None = Field(None, max_length=500)
    api_key: str | None = Field(None, max_length=500)


class WeeklyUpdate(BaseModel):
    enabled: bool | None = None
    day: str | None = Field(None, pattern="^(mon|tue|wed|thu|fri|sat|sun)$")
    time: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    period_days: int | None = None


class GlobalUpdate(BaseModel):
    aggregator: str | None = None
    timeout_s: int | None = Field(None, ge=10, le=600)
    weekly: WeeklyUpdate | None = None


class OpenLinkRequest(BaseModel):
    provider: str
    kind: str = Field(pattern="^(key|pricing)$")


class AnalyzeRequest(BaseModel):
    period_days: int = 7


def _check_provider(svc: Services, pid: str) -> None:
    if pid not in svc.ai.registry:
        raise HTTPException(404, f"Fournisseur inconnu : {pid}")


def _check_period(days: int) -> None:
    if days not in ai_settings.ANALYSIS_PERIODS:
        raise HTTPException(422, f"Période non proposée : {days} j")


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    with connect() as conn:
        view = ai_settings.public_view(ai_settings.load(conn))
    return {**view, "disclaimer": DISCLAIMER}


@router.put("/providers/{pid}")
def update_provider(pid: str, body: ProviderUpdate, svc: Services = Depends(get_services)) -> dict[str, Any]:
    _check_provider(svc, pid)
    patch = body.model_dump(exclude_none=True, exclude={"api_key", "delete_key", "clear_prices"})
    for key in ("model", "base_url"):
        if key in patch:
            patch[key] = patch[key].strip()
    if body.clear_prices:
        patch.update(price_in=None, price_out=None)
    if body.delete_key:
        ai_settings.delete_key(pid)
    elif body.api_key and body.api_key.strip():
        ai_settings.set_key(pid, body.api_key)
    with connect() as conn:
        settings = ai_settings.update_provider(conn, pid, patch)
    return ai_settings.public_view(settings)


@router.post("/providers/{pid}/test")
async def test_provider(pid: str, body: TestRequest, svc: Services = Depends(get_services)) -> dict[str, Any]:
    _check_provider(svc, pid)
    with connect() as conn:
        settings = ai_settings.load(conn)
    overrides = {k: v.strip() for k, v in body.model_dump(exclude_none=True).items() if v.strip()}
    cfg = ai_settings.provider_config(settings, pid, overrides)
    result = await run_in_threadpool(svc.ai.registry[pid].test, cfg)
    return {"ok": result.ok, "message": result.message, "models": result.models,
            "duration_ms": result.duration_ms}


@router.post("/open-link")
async def open_link(body: OpenLinkRequest, svc: Services = Depends(get_services)) -> dict[str, Any]:
    """Ouvre la page de clés ou de tarifs d'un fournisseur dans le navigateur par défaut de Windows.

    Seules les adresses déclarées par les adaptateurs peuvent être ouvertes (aucune URL libre).
    """
    _check_provider(svc, body.provider)
    provider = svc.ai.registry[body.provider]
    url = provider.key_url if body.kind == "key" else provider.pricing_url
    if not url:
        raise HTTPException(404, "Aucun lien pour ce fournisseur")
    if not await run_in_threadpool(webbrowser.open, url, 2):
        raise HTTPException(500, "Impossible d'ouvrir le navigateur")
    return {"opened": url}


@router.put("/settings")
def update_settings(body: GlobalUpdate, svc: Services = Depends(get_services)) -> dict[str, Any]:
    patch = body.model_dump(exclude_none=True)
    agg = patch.get("aggregator")
    if agg is not None and agg not in (ai_settings.AGGREGATOR_AUTO, ai_settings.AGGREGATOR_NONE) \
            and agg not in svc.ai.registry:
        raise HTTPException(422, f"Agrégateur inconnu : {agg}")
    if "weekly" in patch and "period_days" in patch["weekly"]:
        _check_period(patch["weekly"]["period_days"])
    with connect() as conn:
        settings = ai_settings.update_global(conn, patch)
    schedule_weekly_report(svc.scheduler, svc.ai, settings["weekly"])
    return ai_settings.public_view(settings)


@router.get("/summary")
def summary_preview(period_days: int = 7) -> dict[str, Any]:
    """Aperçu exact du résumé qui serait envoyé (transparence)."""
    _check_period(period_days)
    with connect() as conn:
        return build_summary(conn, date.today(), period_days)


@router.post("/analyze")
def analyze(body: AnalyzeRequest, svc: Services = Depends(get_services)) -> dict[str, Any]:
    _check_period(body.period_days)
    try:
        report_id = svc.ai.start(body.period_days, "manual")
    except NoProviderEnabled as exc:
        raise HTTPException(400, str(exc)) from exc
    except AnalysisBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"report_id": report_id}


@router.get("/status")
def status(svc: Services = Depends(get_services)) -> dict[str, Any]:
    st = svc.ai.status()
    job = svc.scheduler.get_job("weekly_ai_report") if svc.scheduler else None
    st["next_weekly_run"] = job.next_run_time.isoformat() if job and job.next_run_time else None
    return st


@router.get("/reports")
def reports(limit: int = 50) -> list[dict[str, Any]]:
    with connect() as conn:
        return store.list_reports(conn, max(1, min(limit, 500)))


@router.get("/reports/{report_id}")
def report(report_id: int) -> dict[str, Any]:
    with connect() as conn:
        rep = store.get_report(conn, report_id)
    if rep is None:
        raise HTTPException(404, "Rapport introuvable")
    return {**rep, "disclaimer": DISCLAIMER, "metric_labels": METRIC_LABELS}


@router.delete("/reports/{report_id}")
def delete_report(report_id: int, svc: Services = Depends(get_services)) -> dict[str, Any]:
    st = svc.ai.status()
    if st.get("running") and st.get("report_id") == report_id:
        raise HTTPException(409, "Analyse en cours : suppression impossible.")
    with connect() as conn:
        if not store.delete_report(conn, report_id):
            raise HTTPException(404, "Rapport introuvable")
    return {"deleted": report_id}

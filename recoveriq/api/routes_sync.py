"""Synchronisation : déclenchement, état courant, journal, aperçu des données."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from recoveriq.api.deps import Services, get_services
from recoveriq.db import repository as repo
from recoveriq.db.database import connect

router = APIRouter(prefix="/api", tags=["sync"])


@router.get("/sync/status")
def sync_status(svc: Services = Depends(get_services)) -> dict:
    return svc.sync.status()


@router.post("/sync/now")
def sync_now(svc: Services = Depends(get_services)) -> dict:
    return {"message": svc.sync.request_incremental("manual")}


@router.post("/sync/backfill")
def sync_backfill(svc: Services = Depends(get_services)) -> dict:
    return {"message": svc.sync.request_backfill("manual")}


@router.get("/sync/runs")
def sync_runs(limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    with connect() as conn:
        return repo.list_runs(conn, limit)


@router.get("/data/overview")
def data_overview() -> list[dict]:
    with connect() as conn:
        return repo.data_overview(conn)

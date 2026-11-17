"""Services partagés par les routes, attachés à ``app.state`` au démarrage."""

from __future__ import annotations

from dataclasses import dataclass

from apscheduler.schedulers.base import BaseScheduler
from fastapi import Request

from recoveriq.ai.service import AnalysisService
from recoveriq.garmin.auth import GarminAuth
from recoveriq.garmin.sync import SyncService


@dataclass
class Services:
    auth: GarminAuth
    sync: SyncService
    ai: AnalysisService
    scheduler: BaseScheduler | None = None


def get_services(request: Request) -> Services:
    return request.app.state.services

"""Connexion Garmin : statut, identifiants, MFA, déconnexion."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from recoveriq.api.deps import Services, get_services

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class MfaRequest(BaseModel):
    code: str = Field(min_length=4, max_length=12)


@router.get("/status")
def auth_status(svc: Services = Depends(get_services)) -> dict:
    return asdict(svc.auth.status())


@router.post("/login")
async def login(body: LoginRequest, svc: Services = Depends(get_services)) -> dict:
    # Appel réseau bloquant (plusieurs secondes) : exécuté hors de la boucle asyncio.
    return asdict(await run_in_threadpool(svc.auth.start_login, body.email, body.password))


@router.post("/mfa")
async def mfa(body: MfaRequest, svc: Services = Depends(get_services)) -> dict:
    return asdict(await run_in_threadpool(svc.auth.submit_mfa, body.code))


@router.post("/logout")
async def logout(svc: Services = Depends(get_services)) -> dict:
    return asdict(await run_in_threadpool(svc.auth.logout))

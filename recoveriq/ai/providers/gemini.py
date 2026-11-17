"""Adaptateur Google Gemini (API generateContent)."""

from __future__ import annotations

from typing import Any

from recoveriq.ai.providers.base import Completion, LLMProvider, ProviderConfig, ProviderError


class GeminiProvider(LLMProvider):
    id = "gemini"
    label = "Google Gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"
    key_help = "Clé Google AI Studio."
    key_url = "https://aistudio.google.com/app/apikey"
    pricing_url = "https://ai.google.dev/gemini-api/docs/pricing"

    def _headers(self, cfg: ProviderConfig) -> dict[str, str]:
        # Clé passée en en-tête (et non dans l'URL) pour ne pas apparaître dans les journaux.
        return {"x-goog-api-key": cfg.api_key or ""}

    def _complete(self, cfg: ProviderConfig, system: str, user: str) -> Completion:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        model = cfg.model.removeprefix("models/")
        data = self._request("POST", f"{self._base_url(cfg)}/models/{model}:generateContent", cfg,
                             headers=self._headers(cfg), json=body)
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason")
            raise ProviderError("aucune réponse générée" + (f" ({reason})" if reason else ""))
        cand = candidates[0]
        if cand.get("finishReason") == "MAX_TOKENS":
            raise ProviderError("réponse tronquée (limite de jetons atteinte)")
        parts = (cand.get("content") or {}).get("parts") or []
        # Les modèles « thinking » peuvent renvoyer des parties de réflexion : on les écarte.
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        usage = data.get("usageMetadata") or {}
        return Completion(text, data.get("modelVersion", model), usage.get("promptTokenCount"),
                          usage.get("candidatesTokenCount"))

    def _list_models(self, cfg: ProviderConfig) -> list[str]:
        models: list[str] = []
        params: dict[str, Any] = {"pageSize": 1000}
        for _ in range(10):  # pagination bornée
            data = self._request("GET", f"{self._base_url(cfg)}/models", cfg,
                                 headers=self._headers(cfg), params=params)
            for m in data.get("models", []):
                if "generateContent" in (m.get("supportedGenerationMethods") or []):
                    models.append(m["name"].removeprefix("models/"))
            token = data.get("nextPageToken")
            if not token:
                break
            params = {"pageSize": 1000, "pageToken": token}
        return models

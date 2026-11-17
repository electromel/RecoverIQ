"""Adaptateurs au format « OpenAI Chat Completions » : OpenAI, Mistral et serveur personnalisé.

Mistral et la plupart des serveurs locaux (Ollama, LM Studio, vLLM…) exposent la même
API ``/chat/completions`` : un seul adaptateur, paramétré par sous-classe.
"""

from __future__ import annotations

from typing import Any

from recoveriq.ai.providers.base import Completion, LLMProvider, ProviderConfig, ProviderError


class OpenAICompatibleProvider(LLMProvider):
    # Demande une sortie JSON stricte quand le service sait le faire.
    json_mode: bool = True

    def _headers(self, cfg: ProviderConfig) -> dict[str, str]:
        return {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}

    def _complete(self, cfg: ProviderConfig, system: str, user: str) -> Completion:
        # Ni « temperature » ni « max_tokens » : certains modèles récents (raisonnement)
        # les refusent ; les valeurs par défaut du service conviennent.
        body: dict[str, Any] = {
            "model": cfg.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        data = self._request("POST", f"{self._base_url(cfg)}/chat/completions", cfg,
                             headers=self._headers(cfg), json=body)
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("aucune réponse générée")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise ProviderError("réponse tronquée (limite de jetons atteinte)")
        content = (choice.get("message") or {}).get("content") or ""
        if isinstance(content, list):  # certains serveurs renvoient des blocs
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        usage = data.get("usage") or {}
        return Completion(content, data.get("model", cfg.model), usage.get("prompt_tokens"),
                          usage.get("completion_tokens"))

    def _list_models(self, cfg: ProviderConfig) -> list[str]:
        data = self._request("GET", f"{self._base_url(cfg)}/models", cfg, headers=self._headers(cfg))
        return [m["id"] for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]


class OpenAIProvider(OpenAICompatibleProvider):
    id = "openai"
    label = "OpenAI (GPT)"
    default_base_url = "https://api.openai.com/v1"
    key_help = "Commence par « sk- »."
    key_url = "https://platform.openai.com/api-keys"
    pricing_url = "https://openai.com/api/pricing/"


class MistralProvider(OpenAICompatibleProvider):
    id = "mistral"
    label = "Mistral AI"
    default_model = "mistral-large-latest"
    default_base_url = "https://api.mistral.ai/v1"
    key_help = "Clé La Plateforme (console Mistral)."
    key_url = "https://console.mistral.ai/api-keys"
    pricing_url = "https://mistral.ai/pricing#api-pricing"


class CustomProvider(OpenAICompatibleProvider):
    """Serveur compatible OpenAI choisi par l'utilisateur (ex. Ollama : http://localhost:11434/v1)."""

    id = "custom"
    label = "Personnalisé (compatible OpenAI)"
    needs_key = False            # Ollama n'en demande pas : facultative
    needs_base_url = True
    json_mode = False            # pas garanti partout ; la réponse est validée de toute façon
    key_help = "Facultative pour un serveur local (Ollama, LM Studio)."
    key_url = "https://github.com/ollama/ollama/blob/main/docs/openai.md"   # compatibilité OpenAI d'Ollama

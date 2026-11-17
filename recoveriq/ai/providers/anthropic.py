"""Adaptateur Anthropic (API Messages)."""

from __future__ import annotations

from recoveriq.ai.providers.base import Completion, LLMProvider, ProviderConfig, ProviderError

API_VERSION = "2023-06-01"
MAX_OUTPUT_TOKENS = 4096


class AnthropicProvider(LLMProvider):
    id = "anthropic"
    label = "Anthropic (Claude)"
    default_model = "claude-sonnet-5-5"
    default_base_url = "https://api.anthropic.com"
    key_help = "Commence par « sk-ant- »."
    key_url = "https://console.anthropic.com/settings/keys"
    pricing_url = "https://www.anthropic.com/pricing#api"

    def _headers(self, cfg: ProviderConfig) -> dict[str, str]:
        return {"x-api-key": cfg.api_key or "", "anthropic-version": API_VERSION}

    def _complete(self, cfg: ProviderConfig, system: str, user: str) -> Completion:
        body = {
            "model": cfg.model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        data = self._request("POST", f"{self._base_url(cfg)}/v1/messages", cfg,
                             headers=self._headers(cfg), json=body)
        if data.get("stop_reason") == "max_tokens":
            raise ProviderError("réponse tronquée (limite de jetons atteinte)")
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage") or {}
        return Completion(text, data.get("model", cfg.model), usage.get("input_tokens"),
                          usage.get("output_tokens"))

    def _list_models(self, cfg: ProviderConfig) -> list[str]:
        data = self._request("GET", f"{self._base_url(cfg)}/v1/models", cfg,
                             headers=self._headers(cfg), params={"limit": 1000})
        return [m["id"] for m in data.get("data", []) if m.get("id")]

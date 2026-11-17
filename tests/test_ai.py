"""Analyse IA : format imposé, comparaison, adaptateurs HTTP, résumé agrégé, orchestration."""

from __future__ import annotations

import json
import time
from datetime import date

import httpx
import pytest

from recoveriq.ai import service as service_mod
from recoveriq.ai import settings as ai_settings
from recoveriq.ai import store
from recoveriq.ai.compare import compare_reports
from recoveriq.ai.providers import Completion, LLMProvider, ProviderConfig, ProviderError, ProviderTimeout
from recoveriq.ai.providers.anthropic import AnthropicProvider
from recoveriq.ai.providers.gemini import GeminiProvider
from recoveriq.ai.providers.openai_compat import CustomProvider, OpenAIProvider
from recoveriq.ai.report_format import ReportFormatError, parse_report
from recoveriq.ai.service import AnalysisService, NoProviderEnabled
from recoveriq.ai.summary import build_summary
from recoveriq.db.database import connect
from recoveriq.devtools.demo_data import populate

TODAY = date(2026, 11, 16)


def report_json(alert_metric="sleep_duration", severity="medium", direction="up", n_sugg=3) -> str:
    return json.dumps({
        "highlights": ["VFC stable"],
        "trends": [{"metric": "hrv", "direction": direction, "comment": "c"}],
        "alerts": [{"metric": alert_metric, "severity": severity, "title": "Sommeil court", "detail": "d"}],
        "suggestions": [{"title": f"S{i}", "detail": "x"} for i in range(n_sugg)],
    })


# --- Format imposé -------------------------------------------------------------------

def test_parse_report_tolerates_fences_and_synonyms():
    text = "Voici :\n```json\n" + json.dumps({
        "highlights": ["a"], "trends": [{"metric": "inconnue", "direction": "hausse"}],
        "alerts": [{"metric": "hrv", "severity": "élevée", "title": "t"}],
        "suggestions": ["un", {"title": "deux"}, {"detail": "trois"}, "quatre"],
    }) + "\n```"
    rep, warnings = parse_report(text)
    assert rep["trends"][0] == {"metric": "general", "direction": "up", "comment": ""}
    assert rep["alerts"][0]["severity"] == "high"
    assert [s["title"] for s in rep["suggestions"]] == ["un", "deux", "trois"]
    assert warnings == ["4 suggestion(s) au lieu de 3"]


def test_parse_report_rejects_unusable_answers():
    with pytest.raises(ReportFormatError):
        parse_report("Je ne peux pas répondre.")
    with pytest.raises(ReportFormatError):
        parse_report('{"foo": 1}')


# --- Comparaison déterministe ----------------------------------------------------------

def test_compare_reports_consensus_isolated_and_severity_gaps():
    a, _ = parse_report(report_json("sleep_duration", "medium", "up"))
    b, _ = parse_report(report_json("sleep_duration", "high", "down"))
    c, _ = parse_report(report_json("stress_avg", "low", "up"))
    cmp = compare_reports({"a": a, "b": b, "c": c})
    assert [e["metric"] for e in cmp["consensus_alerts"]] == ["sleep_duration"]
    assert cmp["consensus_alerts"][0]["max_severity"] == "high"
    assert [e["metric"] for e in cmp["severity_differences"]] == ["sleep_duration"]
    assert [e["metric"] for e in cmp["isolated_alerts"]] == ["stress_avg"]
    assert cmp["trends"][0]["agreement"] == "conflict"


# --- Adaptateurs (HTTP simulé) ------------------------------------------------------------

def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_anthropic_adapter_request_and_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers["x-api-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"model": "claude-x", "stop_reason": "end_turn",
                                         "content": [{"type": "text", "text": "{}"}],
                                         "usage": {"input_tokens": 100, "output_tokens": 20}})

    out = AnthropicProvider(mock_client(handler)).complete(ProviderConfig("claude-x", "sk-ant-1"), "sys", "usr")
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["key"] == "sk-ant-1"
    assert seen["body"]["system"] == "sys" and seen["body"]["messages"][0]["content"] == "usr"
    assert (out.text, out.input_tokens, out.output_tokens) == ("{}", 100, 20)


def test_openai_and_custom_adapters():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append((str(request.url), request.headers.get("authorization"), json.loads(request.content)))
        return httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 5, "completion_tokens": 7}})

    OpenAIProvider(mock_client(handler)).complete(ProviderConfig("gpt", "sk-1"), "s", "u")
    CustomProvider(mock_client(handler)).complete(
        ProviderConfig("llama", None, "http://localhost:11434/v1/"), "s", "u")
    assert bodies[0][0] == "https://api.openai.com/v1/chat/completions"
    assert bodies[0][1] == "Bearer sk-1" and bodies[0][2]["response_format"] == {"type": "json_object"}
    assert bodies[1][0] == "http://localhost:11434/v1/chat/completions"
    assert bodies[1][1] is None and "response_format" not in bodies[1][2]


def test_gemini_adapter_skips_thoughts_and_lists_models():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "g-1"
        assert "key=" not in str(request.url)
        if request.method == "GET":
            return httpx.Response(200, json={"models": [
                {"name": "models/gemini-a", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/embed", "supportedGenerationMethods": ["embedContent"]}]})
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": "réflexion", "thought": True}, {"text": "{\"a\":1}"}]}}],
            "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 4}})

    provider = GeminiProvider(mock_client(handler))
    out = provider.complete(ProviderConfig("gemini-a", "g-1"), "s", "u")
    assert out.text == '{"a":1}'
    test = provider.test(ProviderConfig("gemini-a", "g-1"))
    assert test.ok and test.models == ["gemini-a"]


def test_http_errors_are_translated():
    def unauthorized(request):
        return httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})

    with pytest.raises(ProviderError, match="401.*clé API refusée.*invalid x-api-key"):
        AnthropicProvider(mock_client(unauthorized)).complete(ProviderConfig("m", "k"), "s", "u")

    def slow(request):
        raise httpx.ReadTimeout("lent", request=request)

    with pytest.raises(ProviderTimeout):
        OpenAIProvider(mock_client(slow)).complete(ProviderConfig("m", "k"), "s", "u")

    assert not OpenAIProvider().test(ProviderConfig("m", None)).ok   # clé manquante, aucun appel réseau


# --- Résumé agrégé -----------------------------------------------------------------------

def test_summary_contains_only_aggregates(db):
    with connect() as conn:
        populate(conn, 200, TODAY)
        summary = build_summary(conn, TODAY, 28)
    assert summary["period"] == {"start": "2026-10-20", "end": "2026-11-16", "days": 28}
    assert summary["reference_period"]["days"] == 112
    hrv = next(m for m in summary["metrics"] if m["key"] == "hrv")
    assert hrv["days_with_data"] > 20 and hrv["reference"]["status"] in ("normal", "above", "below")
    assert summary["correlations"]

    # Aucune série journalière : pas de liste de nombres, ni de date hors bornes de période.
    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            assert not (len(node) > 3 and all(isinstance(x, (int, float)) for x in node))
            for v in node:
                walk(v)
    walk(summary)
    text = json.dumps(summary)
    assert "2026-11-01" not in text


# --- Orchestration -----------------------------------------------------------------------

class FakeProvider(LLMProvider):
    def __init__(self, pid: str, text: str | None = None, error: Exception | None = None, delay: float = 0) -> None:
        super().__init__()
        self.id, self.label = pid, pid.upper()
        self.text, self.error, self.delay = text, error, delay
        self.calls = []

    def _complete(self, cfg, system, user):
        self.calls.append(system)
        time.sleep(self.delay)
        if self.error:
            raise self.error
        if "synthèse" in system:
            return Completion(json.dumps({"summary": "Résumé.", "consensus": ["c"], "divergences": [],
                                          "suggestions": [{"title": "s"}]}), cfg.model, 10, 5)
        return Completion(self.text, cfg.model, 1000, 200)

    def _list_models(self, cfg):
        return [cfg.model]


@pytest.fixture()
def ai_db(db, monkeypatch):
    monkeypatch.setattr(ai_settings, "get_key", lambda pid: "cle-test")
    with connect() as conn:
        populate(conn, 120, TODAY)
    return db


def enable(conn, *pids, **extra):
    for pid in pids:
        ai_settings.update_provider(conn, pid, {"enabled": True, "model": f"{pid}-model", **extra})


def test_analysis_with_failures_and_llm_synthesis(ai_db):
    registry = {
        "anthropic": FakeProvider("anthropic", report_json()),
        "openai": FakeProvider("openai", report_json(severity="high")),
        "gemini": FakeProvider("gemini", error=ProviderError("HTTP 401 : clé API refusée")),
        "mistral": FakeProvider("mistral", "pas du JSON"),
        "custom": FakeProvider("custom", report_json()),
    }
    with connect() as conn:
        enable(conn, "anthropic", "openai", "gemini", "mistral", price_in=3.0, price_out=15.0)
    svc = AnalysisService(registry, today=lambda: TODAY)
    rid = svc.run_blocking(7)

    with connect() as conn:
        rep = store.get_report(conn, rid)
    status = {r["provider"]: r["status"] for r in rep["results"]}
    assert status == {"anthropic": "ok", "openai": "ok", "gemini": "error", "mistral": "invalid"}
    assert rep["status"] == "partial"
    assert rep["synthesis_mode"] == "llm" and rep["aggregator"] == "anthropic"
    assert rep["synthesis"]["summary"] == "Résumé."
    assert rep["comparison"]["severity_differences"][0]["metric"] == "sleep_duration"
    # 3 appels facturés (2 rapports OK + 1 invalide) + la synthèse : 3 × (1000×3 + 200×15)/1e6 + (10×3 + 5×15)/1e6
    assert rep["total_cost"] == pytest.approx(3 * 0.006 + 0.000105)
    assert rep["summary"]["period"]["days"] == 7
    assert registry["custom"].calls == []          # fournisseur non activé : jamais appelé
    assert not svc.status()["running"]


def test_single_provider_and_aggregator_fallback(ai_db):
    registry = {"anthropic": FakeProvider("anthropic", report_json()),
                "openai": FakeProvider("openai", report_json())}
    with connect() as conn:
        enable(conn, "anthropic")
    svc = AnalysisService(registry, today=lambda: TODAY)
    with connect() as conn:
        rep = store.get_report(conn, svc.run_blocking(7))
    assert rep["status"] == "success" and rep["synthesis_mode"] == "single" and rep["comparison"] is None
    assert rep["total_cost"] is None and rep["cost_complete"] == 0   # tarifs non renseignés

    with connect() as conn:
        enable(conn, "openai")
        ai_settings.update_global(conn, {"aggregator": ""})
    with connect() as conn:
        rep = store.get_report(conn, svc.run_blocking(7))
    assert rep["synthesis_mode"] == "fallback" and rep["comparison"]["consensus_alerts"]


def test_slow_provider_times_out_without_blocking_others(ai_db, monkeypatch):
    monkeypatch.setattr(service_mod, "WAIT_MARGIN_S", 0)
    registry = {"anthropic": FakeProvider("anthropic", report_json()),
                "openai": FakeProvider("openai", report_json(), delay=3)}
    with connect() as conn:
        enable(conn, "anthropic", "openai")
        ai_settings.update_global(conn, {"timeout_s": 0.5})
    started = time.monotonic()
    rid = AnalysisService(registry, today=lambda: TODAY).run_blocking(7)
    assert time.monotonic() - started < 2.5
    with connect() as conn:
        rep = store.get_report(conn, rid)
    assert {r["provider"]: r["status"] for r in rep["results"]} == {"anthropic": "ok", "openai": "timeout"}
    assert rep["status"] == "partial" and rep["synthesis_mode"] == "single"


def test_no_provider_enabled(ai_db):
    with pytest.raises(NoProviderEnabled):
        AnalysisService({}, today=lambda: TODAY).start(7)

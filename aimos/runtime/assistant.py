"""Read-only AI analyst (§15.3 sensor/explainer role, specs/ASSISTANT.md).

Answers natural-language questions about the running system — grounded in the
journal + real metrics, never freelancing — and generates timeframe reports. It
is strictly READ-ONLY: it assembles an evidence bundle from read-only providers,
hands it to the LLM with a locked analyst system prompt, and returns a cited
answer. It cannot place trades, flip flags, or edit config; any action it
recommends is executed by the human through the existing CONFIRM-gated controls.

The LLM caller is an injected callable (a plain httpx POST to the Anthropic
Messages API), so the grounding + prompting is fully testable with no network.
Off unless enabled + ANTHROPIC_API_KEY. Not in the magic-number-linted layers.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import structlog

log = structlog.get_logger(__name__)

_DEF_MODEL = "claude-sonnet-5"
_DEF_OPENAI_MODEL = "gpt-4o-mini"   # cheap default; override via assistant.openai_model
_DEF_MAX_TOKENS = 1200
_DEF_TEMPERATURE = 0.2
_DEF_TIMEOUT = 40.0
_DEF_RECENT = 40
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"

_SYSTEM = (
    "You are AIMOS Analyst, a READ-ONLY assistant for a deterministic crypto "
    "trading system. Answer ONLY from the JSON evidence provided — it is the "
    "system's own journal and metrics. Rules you must obey:\n"
    "1. Ground every claim in the evidence; cite decision_ids and exact numbers. "
    "Never invent figures. If the evidence does not answer the question, say so "
    "plainly.\n"
    "2. You CANNOT take actions — you may RECOMMEND (e.g. 'consider disabling X', "
    "'train more history', 'keep paper-trading'), but a human executes any change "
    "through confirmed controls. Frame recommendations as advice, not commands.\n"
    "3. Be honest about limits: paper/backtest results are NOT a proven live edge; "
    "an ML fusion weight of 0 means the model is in shadow and NOT trusted yet.\n"
    "4. Be concise, specific, and quantitative."
)

_REPORT_Q = (
    "Generate a performance + health report for the last {tf}. Cover: what the "
    "system did (decision/trade counts, NO_TRADE rate), which strategies and "
    "decisions worked vs didn't, whether the ML is working (shadow AUC / loaded / "
    "fusion weight), any issues or anomalies you can see in the evidence, and "
    "concrete advisory recommendations (more paper trading? train more on "
    "history? disable a method?). Ground every point in the evidence."
)


class AssistantDisabled(RuntimeError):
    """The analyst is off or has no API key — callers should surface a 503."""


# ---------------------------------------------------------------------------
# grounding (deterministic, read-only) — the testable core
# ---------------------------------------------------------------------------


def _parse_timeframe(tf: str) -> Optional[timedelta]:
    """'24h' / '7d' / '30m' / '2w' → timedelta; None if unparseable."""
    tf = (tf or "").strip().lower()
    if not tf or tf[-1] not in "mhdw" or not tf[:-1].isdigit():
        return None
    n = int(tf[:-1])
    return {"m": timedelta(minutes=n), "h": timedelta(hours=n),
            "d": timedelta(days=n), "w": timedelta(weeks=n)}[tf[-1]]


def _call(provider: Optional[Callable], *args) -> Any:
    if provider is None:
        return None
    try:
        return provider(*args)
    except Exception:  # noqa: BLE001 — a broken provider must not crash the analyst
        log.exception("assistant_provider_failed")
        return None


def build_grounding(providers: dict[str, Callable], recent: int = _DEF_RECENT,
                    timeframe: Optional[str] = None) -> dict:
    """Assemble the read-only evidence bundle the LLM reasons over.

    ``providers`` is a dict of read-only callables (all optional): ``decisions``
    (limit)→list, ``performance``/``models``/``monitor``/``features``/``golive``/
    ``strategies``()→dict, ``equity``()→list. Only present keys are used.
    """
    decisions = _call(providers.get("decisions"), recent) or []
    window = None
    if timeframe:
        delta = _parse_timeframe(timeframe)
        if delta is not None:
            cutoff = datetime.now(timezone.utc) - delta
            kept = []
            for d in decisions:
                ts = _ts(d.get("timestamp"))
                if ts is None or ts >= cutoff:
                    kept.append(d)
            decisions, window = kept, timeframe

    equity = _call(providers.get("equity")) or []
    grounding = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": window,
        "decisions": decisions,
        "n_decisions_in_bundle": len(decisions),
        "performance": _call(providers.get("performance")) or {},
        "models": _call(providers.get("models")) or {},
        "monitor": _call(providers.get("monitor")) or {},
        "features": _call(providers.get("features")) or {},
        "golive": _call(providers.get("golive")) or {},
        "strategies": _call(providers.get("strategies")) or {},
        "equity": {"start": equity[0] if equity else None,
                   "last": equity[-1] if equity else None,
                   "points": len(equity)},
    }
    return grounding


def _ts(v: Any) -> Optional[datetime]:
    if not isinstance(v, str):
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _grounding_summary(g: dict) -> dict:
    """A tiny, non-sensitive descriptor of what the answer was grounded on (for UI)."""
    return {"window": g.get("window"), "decisions": g.get("n_decisions_in_bundle"),
            "equity_points": g.get("equity", {}).get("points"),
            "monitor_coverage": g.get("monitor", {}).get("coverage_pct")}


def _user_prompt(question: str, grounding: dict) -> str:
    return (f"{question}\n\nEVIDENCE (read-only system state, JSON):\n"
            f"{json.dumps(grounding, default=str)}")


# ---------------------------------------------------------------------------
# LLM caller (injected; default = plain httpx POST to Anthropic)
# ---------------------------------------------------------------------------


def anthropic_caller(system: str, user: str, *, model: str, max_tokens: int,
                     temperature: float, timeout: float) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise AssistantDisabled("ANTHROPIC_API_KEY not set")
    import httpx
    r = httpx.post(
        _ANTHROPIC_URL,
        headers={"x-api-key": key, "anthropic-version": _ANTHROPIC_VERSION,
                 "content-type": "application/json"},
        json={"model": model, "max_tokens": max_tokens, "temperature": temperature,
              "system": system, "messages": [{"role": "user", "content": user}]},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()


def openai_caller(system: str, user: str, *, model: str, max_tokens: int,
                  temperature: float, timeout: float) -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise AssistantDisabled("OPENAI_API_KEY not set")
    import httpx
    r = httpx.post(
        _OPENAI_URL,
        headers={"authorization": f"Bearer {key}", "content-type": "application/json"},
        json={"model": model, "max_tokens": max_tokens, "temperature": temperature,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}]},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    return ((data.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()


def caller_for(cfg: Optional[dict]) -> Callable:
    """Pick the LLM backend from ``assistant.provider`` (anthropic | openai)."""
    provider = (cfg or {}).get("provider", "anthropic")
    return openai_caller if str(provider).lower() == "openai" else anthropic_caller


# ---------------------------------------------------------------------------
# the analyst
# ---------------------------------------------------------------------------


class Assistant:
    def __init__(self, providers: dict[str, Callable], cfg: Optional[dict] = None,
                 caller: Optional[Callable] = None) -> None:
        self.providers = providers
        self.cfg = cfg or {}
        self.caller = caller or caller_for(self.cfg)  # anthropic | openai per config
        self.recent = int(self.cfg.get("recent_decisions", _DEF_RECENT))

    def answer(self, question: str) -> dict:
        question = (question or "").strip()
        if not question:
            return {"answer": "Ask me anything about the system — decisions, "
                              "performance, the ML, or what to do next.", "grounded_on": {}}
        g = build_grounding(self.providers, recent=self.recent)
        text = self._llm(_user_prompt(question, g))
        return {"answer": text, "grounded_on": _grounding_summary(g)}

    def report(self, timeframe: str = "24h") -> dict:
        g = build_grounding(self.providers, recent=max(self.recent, 200), timeframe=timeframe)
        text = self._llm(_user_prompt(_REPORT_Q.format(tf=timeframe), g))
        return {"report": text, "timeframe": timeframe, "grounded_on": _grounding_summary(g)}

    def _model(self) -> str:
        if str(self.cfg.get("provider", "anthropic")).lower() == "openai":
            return self.cfg.get("openai_model", _DEF_OPENAI_MODEL)
        return self.cfg.get("model", _DEF_MODEL)

    def _llm(self, user: str) -> str:
        return self.caller(
            _SYSTEM, user,
            model=self._model(),
            max_tokens=int(self.cfg.get("max_tokens", _DEF_MAX_TOKENS)),
            temperature=float(self.cfg.get("temperature", _DEF_TEMPERATURE)),
            timeout=float(self.cfg.get("timeout_seconds", _DEF_TIMEOUT)),
        )


__all__ = ["Assistant", "AssistantDisabled", "anthropic_caller", "build_grounding",
           "caller_for", "openai_caller"]

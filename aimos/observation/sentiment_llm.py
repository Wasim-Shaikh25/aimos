"""LLM news sensor (§19, card P6-T3).

The LLM enters the OBSERVATION layer only, as an upgraded sentiment engine that
converts unstructured headlines → structured Evidence. It is a sensor with a
reliability score, not a reasoner. Defenses (all mandatory, §19.2):

* strict pydantic schema — any non-conforming output discards the batch and falls
  back to the lexicon (§5.10);
* magnitude/credibility clamped to [0, 1];
* asset allowlist against real registry bases;
* determinism — every call's input hash + parsed output is cached; replay reads
  ONLY the cache (a miss is a hard error, never a live call).

The LLM itself is an injected ``classifier`` callable so this is testable with no
network. Thresholds from config; the magic-number lint governs this module.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Callable, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aimos.core.evidence_registry import is_registered
from aimos.core.schemas import Direction, Evidence, Headline, Timeframe

Classifier = Callable[[Sequence[dict]], str]  # headlines → raw JSON string


class ReplayCacheMiss(RuntimeError):
    """A cache miss in replay mode — never fall back to a live LLM call (§19.3)."""


class NewsClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    assets: list[str]
    event_type: str
    direction: str
    magnitude: float = Field(ge=0, le=1)
    credibility: float = Field(ge=0, le=1)
    time_horizon: str
    one_line_rationale: str

    @field_validator("magnitude", "credibility", mode="before")
    @classmethod
    def _clamp(cls, v: Any) -> float:
        return max(0.0, min(1.0, float(v)))


def _direction(value: str) -> Direction:
    return {"bullish": Direction.BULLISH, "bearish": Direction.BEARISH}.get(value, Direction.NEUTRAL)


class LLMNewsSensor:
    def __init__(
        self,
        cfg: Mapping[str, Any],
        reliability: float,
        classifier: Optional[Classifier] = None,
        cache: Optional[dict[str, str]] = None,
        replay: bool = False,
    ) -> None:
        self.llm_cfg = cfg["sentiment_llm"]
        self.reliability = reliability
        self.classifier = classifier
        self.cache = cache if cache is not None else {}
        self.replay = replay

    def classify(self, headlines: Sequence[Headline]) -> Optional[list[NewsClassification]]:
        """Return parsed classifications, or None → caller uses lexicon fallback."""
        payload = [{"id": i, "title": h.title} for i, h in enumerate(headlines)]
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        if key in self.cache:
            raw = self.cache[key]
        elif self.replay:
            raise ReplayCacheMiss(f"no cached LLM output for {key} in replay mode (§19.3)")
        elif self.classifier is not None:
            raw = self.classifier(payload)
            self.cache[key] = raw  # freeze for deterministic replay
        else:
            return None
        return self._parse(raw)

    def _parse(self, raw: str) -> Optional[list[NewsClassification]]:
        try:
            data = json.loads(raw)
            return [NewsClassification.model_validate(item) for item in data]
        except Exception:  # noqa: BLE001 — malformed → discard batch, fall back
            return None

    def to_evidence(
        self, classification: NewsClassification, registry_bases: set[str], now: datetime
    ) -> list[Evidence]:
        """Map one classification to Evidence (+ headline_shock when warranted)."""
        out: list[Evidence] = []
        # asset allowlist: only real registry bases (injection defense)
        assets = [a for a in classification.assets if a.upper() in registry_bases or a == "MARKET"]
        if not assets:
            return out
        name = f"news_{classification.event_type}"
        if not is_registered(name):
            name = "news_other"
        strength = classification.magnitude * classification.credibility
        for asset in assets:
            out.append(Evidence(
                source="sentiment_llm.classifier", symbol=asset, timeframe=Timeframe.H1,
                timestamp=now, name=name, value=strength,
                direction=_direction(classification.direction),
                strength=strength, reliability=self.reliability,
                meta={"event_type": classification.event_type, "credibility": classification.credibility},
            ))
            # shock gate: hack/exploit/bankruptcy/delisting with high credibility
            if (classification.event_type in self.llm_cfg["shock_event_types"]
                    and classification.credibility >= float(self.llm_cfg["shock_credibility_min"])):
                out.append(Evidence(
                    source="sentiment_llm.shock", symbol=asset, timeframe=Timeframe.H1,
                    timestamp=now, name="headline_shock", value=1.0, direction=Direction.BEARISH,
                    strength=1.0, reliability=self.reliability,
                    meta={"risk_gate": True, "event_type": classification.event_type},
                ))
        return out


__all__ = ["LLMNewsSensor", "NewsClassification", "ReplayCacheMiss"]

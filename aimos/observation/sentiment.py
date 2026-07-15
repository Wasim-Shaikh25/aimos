"""Sentiment engine — keyword lexicon (§5.10, card P2-T5).

Emits news_tone (lexicon tone over recent headlines) and headline_shock (a hard
risk gate for hack/exploit/bankruptcy/ban terms). A simple negation guard keeps
denial headlines ("X denies hack rumors") from false-firing the shock gate.

SPEC-GAP (§5.10 rule 1): fear_greed needs the market-wide F&G index, which
``MarketContext`` (§25.1) does not carry — ``fear_greed_strength`` is provided as
a pure helper (tested) for the pipeline to emit once F&G is wired in; the engine
itself emits news_tone + headline_shock from ctx.headlines. The negation guard is
a documented lexicon limitation the §19 LLM sensor resolves fully.
"""

from __future__ import annotations

from datetime import timedelta

from aimos.core.schemas import Direction, Evidence, MarketContext, Timeframe
from aimos.observation.base import ObservationEngine


def fear_greed_strength(index: float, low: float, high: float, div: float) -> tuple[Direction, float]:
    """Contrarian F&G read (§5.10 rule 1): <low → bullish, >high → bearish."""
    if index < low:
        return Direction.BULLISH, min((low - index) / div, 1.0)
    if index > high:
        return Direction.BEARISH, min((index - high) / div, 1.0)
    return Direction.NEUTRAL, 0.0


class SentimentEngine(ObservationEngine):
    name = "sentiment_engine"

    def observe(self, ctx: MarketContext) -> list[Evidence]:
        sc = self.cfg["sentiment"]
        out: list[Evidence] = []
        window = [
            h for h in ctx.headlines
            if h.timestamp >= ctx.now - timedelta(hours=int(sc["news_window_hours"]))
        ]
        if not window:
            return out

        bull = [t.lower() for t in sc["bull_terms"]]
        bear = [t.lower() for t in sc["bear_terms"]]
        shock_terms = [t.lower() for t in sc["shock_terms"]]
        negations = [n.lower() for n in self.cfg["sentiment_negation_cues"]]

        bull_hits = sum(self._count_terms(h.title, bull) for h in window)
        bear_hits = sum(self._count_terms(h.title, bear) for h in window)
        total = bull_hits + bear_hits

        # rule 2: news tone
        if total > 0:
            tone = (bull_hits - bear_hits) / total
            if tone != 0:
                out.append(self._ev(ctx, ctx.now, "news_tone", tone,
                                     Direction.BULLISH if tone > 0 else Direction.BEARISH,
                                     abs(tone)))

        # rule 3: headline shock (last shock_window_min), negation-guarded
        shock_window = [
            h for h in window
            if h.timestamp >= ctx.now - timedelta(minutes=int(sc["headline_shock_window_min"]))
        ]
        for h in shock_window:
            title = h.title.lower()
            if any(term in title for term in shock_terms) and not self._is_negated(title, negations):
                out.append(self._ev(ctx, ctx.now, "headline_shock", 1.0, Direction.BEARISH, 1.0,
                                    {"risk_gate": True, "headline": h.title}))
                break
        return out

    @staticmethod
    def _count_terms(text: str, terms: list[str]) -> int:
        low = text.lower()
        return sum(1 for t in terms if t in low)

    @staticmethod
    def _is_negated(title: str, negations: list[str]) -> bool:
        return any(cue in title for cue in negations)

    def _ev(self, ctx, ts, name, value, direction, strength, meta=None) -> Evidence:
        return Evidence(
            source=f"{self.name}.{name}", symbol=ctx.symbol, timeframe=Timeframe.H1,
            timestamp=ts, name=name, value=float(value), direction=direction,
            strength=self._clamp01(float(strength)), reliability=self.reliability, meta=meta or {},
        )


__all__ = ["SentimentEngine", "fear_greed_strength"]

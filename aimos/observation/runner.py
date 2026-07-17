"""Observation-layer assembly + per-engine isolation (§5, §10.1).

``build_engines`` constructs all 13 engines from ``Params`` (config subtree +
per-engine reliability prior from weights.yaml). ``run_all`` runs them over a
``MarketContext`` with per-engine try/except so one failing engine logs and is
skipped — evidence_coverage drops and confidence self-reduces (§6.7), the
pipeline never crashes on a single engine (§10.1).
"""

from __future__ import annotations

from typing import Any

import structlog

from aimos.core.clock import Clock
from aimos.core.normalize import HALF
from aimos.core.schemas import EvidenceBundle, MarketContext
from aimos.observation.base import ObservationEngine
from aimos.observation.correlation import CorrelationEngine
from aimos.observation.cross_exchange import CrossExchangeEngine
from aimos.observation.funding_engine import FundingEngine
from aimos.observation.liquidity import LiquidityEngine
from aimos.observation.momentum import MomentumEngine
from aimos.observation.onchain_engine import OnchainEngine
from aimos.observation.orderbook_engine import OrderBookEngine
from aimos.observation.price_action import PriceActionEngine
from aimos.observation.sentiment import SentimentEngine
from aimos.observation.time_engine import TimeEngine
from aimos.observation.volatility import VolatilityEngine
from aimos.observation.volume import VolumeEngine
from aimos.observation.whale import WhaleEngine

log = structlog.get_logger(__name__)

# engine class → reliability key in weights.yaml (§5.0)
_ENGINE_SPECS: list[tuple[type[ObservationEngine], str]] = [
    (PriceActionEngine, "price_action"),
    (VolumeEngine, "volume"),
    (MomentumEngine, "momentum"),
    (VolatilityEngine, "volatility"),
    (LiquidityEngine, "liquidity"),
    (OrderBookEngine, "orderbook"),
    (FundingEngine, "funding"),
    (WhaleEngine, "whale"),
    (OnchainEngine, "onchain"),
    (SentimentEngine, "sentiment"),
    (CrossExchangeEngine, "cross_exchange"),
    (CorrelationEngine, "correlation"),
    (TimeEngine, "time"),
]


def build_engines(params: Any, clock: Clock) -> list[ObservationEngine]:
    """Construct all observation engines from ``Params``."""
    obs_cfg = params.observation.model_dump()
    reliabilities = params.weights.model_dump().get("reliability", {})
    engines: list[ObservationEngine] = []
    for cls, key in _ENGINE_SPECS:
        engines.append(cls(cfg=obs_cfg, clock=clock, reliability=float(reliabilities.get(key, HALF))))
    # Scalp proxy micro-engine — only when scalping is feature-flagged on (§17)
    feats = params.features.model_dump() if hasattr(params.features, "model_dump") else {}
    if feats.get("scalp_enabled"):
        from aimos.observation.scalp_micro import ScalpMicroEngine
        engines.append(ScalpMicroEngine(cfg=obs_cfg, clock=clock,
                                        reliability=float(reliabilities.get("scalp_micro", HALF))))
    return engines


def run_all(engines: list[ObservationEngine], ctx: MarketContext) -> EvidenceBundle:
    """Run every engine with per-engine isolation; assemble the bundle (§10.1)."""
    evidences = []
    for eng in engines:
        try:
            evidences.extend(eng.observe(ctx))
        except Exception:  # noqa: BLE001 — graceful degradation (§10.1)
            log.exception("observation_engine_failed", engine=eng.name)
    return EvidenceBundle(symbol=ctx.symbol, timestamp=ctx.now, evidences=evidences)


def engines_reporting(bundle: EvidenceBundle) -> set[str]:
    """Distinct engine source-prefixes that produced ≥1 evidence (for §6.7 coverage)."""
    return {e.source.split(".")[0] for e in bundle.evidences}


__all__ = ["build_engines", "engines_reporting", "run_all"]

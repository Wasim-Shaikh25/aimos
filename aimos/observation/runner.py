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

from aimos.core.clock import BacktestClock, Clock
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


def _build_onchain_provider(onchain_cfg: dict[str, Any]) -> Any | None:
    """Instantiate an on-chain data provider from observation config (REQ-16)."""
    if not onchain_cfg.get("enabled"):
        return None
    provider = onchain_cfg.get("provider", "").lower()
    if provider == "coinmetrics":
        from aimos.data.onchain import CoinMetricsCommunityProvider

        return CoinMetricsCommunityProvider(
            api_key=str(onchain_cfg.get("api_key", "")),
            stablecoin_asset=str(onchain_cfg.get("stablecoin_asset", "usdt")),
        )
    if provider == "freeapi":
        from aimos.data.onchain import FreeApiOnchainProvider

        return FreeApiOnchainProvider(endpoints=onchain_cfg.get("freeapi_endpoints", {}))
    return None

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
    onchain_provider = _build_onchain_provider(obs_cfg.get("onchain", {}))
    for cls, key in _ENGINE_SPECS:
        kwargs: dict[str, Any] = {"cfg": obs_cfg, "clock": clock, "reliability": float(reliabilities.get(key, HALF))}
        if cls is OnchainEngine:
            kwargs["provider"] = onchain_provider
        engines.append(cls(**kwargs))
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


def required_warmup(params: Any) -> int:
    """Minimum warmup bars so all candle-based indicators have converged (T-013).

    Each engine that consumes candles already advertises ``_min_bars`` from its
    own config. We take the maximum so the first labeled/traded bar is computed
    from a buffer that is long enough for every active engine.
    """
    engines = build_engines(params, BacktestClock())
    mins = [int(e._min_bars()) for e in engines if hasattr(e, "_min_bars") and callable(e._min_bars)]
    return max(mins) if mins else 0


__all__ = ["build_engines", "engines_reporting", "required_warmup", "run_all"]

"""Coin health / risk / opportunity scorers (§6.6, card P3-T4).

All 0–100 weighted sums (component weights in weights.yaml). Inputs that need
candle/venue *history* — depth/volume percentiles, exchange quality, portfolio
exposure — are not visible to Layer 2 (§25.3), so they default from config and
the pipeline may override them via ``ScoreContext``. The bundle-derivable inputs
(trend strength, manipulation flags, event flags, regime) are computed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from aimos.core.normalize import HALF, PCT, clamp01
from aimos.core.schemas import Behavior, Direction, EvidenceBundle, Regime
from aimos.intelligence.base import first_named, has_name


@dataclass
class ScoreContext:
    """Optional external inputs the pipeline can supply (else config defaults)."""

    exchange: Optional[str] = None
    liquidity_percentile: Optional[float] = None  # depth vs 30d history
    volume_percentile: Optional[float] = None
    atr_percentile: Optional[float] = None  # ATR% vs history
    portfolio_component: Optional[float] = None
    nearest_opposing_distance_atr: Optional[float] = None  # for rr_potential


def _wsum(weighted: list[tuple[float, float]]) -> float:
    """Weighted average where weights sum to 100 and each value is 0-100."""
    total_w = sum(w for w, _ in weighted)
    if total_w <= 0:
        return 0.0
    return sum(w * v for w, v in weighted) / total_w


def coin_health(
    bundle: EvidenceBundle,
    behavior_probs: Mapping[str, float],
    trend_strength: float,
    weights: Mapping[str, Any],
    scores_cfg: Mapping[str, Any],
    ctx: ScoreContext,
    exchange_quality: Mapping[str, float],
) -> float:
    w = weights["coin_health"]
    liquidity_q = (
        float(scores_cfg["thin_book_q"]) if has_name(bundle.evidences, "thin_book")
        else _val(ctx.liquidity_percentile, scores_cfg["default_liquidity_q"])
    )
    manip_prob = behavior_probs.get(Behavior.MANIPULATION.value, 0.0)
    manipulation_risk = PCT if (
        manip_prob > float(scores_cfg["manipulation_behavior_threshold"])
        or _has_spoof(bundle) or has_name(bundle.evidences, "venue_divergence_volume")
    ) else manip_prob * PCT
    exchange_q = float(exchange_quality.get(ctx.exchange, scores_cfg["default_exchange_q"]))
    volume_q = _val(ctx.volume_percentile, scores_cfg["default_volume_q"])
    trend_q = clamp01(abs(trend_strength)) * PCT
    return _wsum([
        (float(w["liquidity_q"]), liquidity_q),
        (float(w["manipulation_inv"]), PCT - manipulation_risk),
        (float(w["exchange_q"]), exchange_q),
        (float(w["volume_q"]), volume_q),
        (float(w["trend_q"]), trend_q),
    ])


def risk_score(
    bundle: EvidenceBundle,
    regime: Regime,
    weights: Mapping[str, Any],
    scores_cfg: Mapping[str, Any],
    ctx: ScoreContext,
) -> float:
    w = weights["risk_score"]
    regime_values = w["regime_values"]
    vol_pct = _val(ctx.atr_percentile, scores_cfg["default_vol_percentile"])
    if has_name(bundle.evidences, "vol_shock"):
        vol_pct = max(vol_pct, float(w["vol_shock_floor"]))
    liquidity_component = _liquidity_risk(bundle, scores_cfg)
    regime_component = float(regime_values.get(regime.value, 0.0))
    event_component = _event_risk(bundle, w)
    portfolio_component = _val(ctx.portfolio_component, scores_cfg["default_portfolio_component"])
    return clamp0_100(_wsum([
        (float(w["vol_component"]), vol_pct),
        (float(w["liquidity_component"]), liquidity_component),
        (float(w["regime_component"]), regime_component),
        (float(w["event_component"]), event_component),
        (float(w["portfolio_component"]), portfolio_component),
    ]))


def opportunity(
    p_up: float,
    confidence: float,
    direction_bias: Direction,
    regime: Regime,
    health: float,
    weights: Mapping[str, Any],
    scores_cfg: Mapping[str, Any],
    ctx: ScoreContext,
) -> float:
    w = weights["opportunity"]
    edge = clamp01(abs(p_up - HALF) * 2.0) * confidence * PCT
    regime_alignment = _regime_alignment(direction_bias, regime, scores_cfg)
    rr = _rr_potential(ctx, scores_cfg, float(w["rr_potential_cap"]))
    return clamp0_100(_wsum([
        (float(w["edge"]), edge),
        (float(w["regime_alignment"]), regime_alignment),
        (float(w["coin_health"]), health),
        (float(w["rr_potential"]), rr),
    ]))


# -- helpers -----------------------------------------------------------------


def _val(provided: Optional[float], default: Any) -> float:
    return float(provided) if provided is not None else float(default)


def clamp0_100(x: float) -> float:
    return max(0.0, min(PCT, x))


def _has_spoof(bundle: EvidenceBundle) -> bool:
    return any(e.meta.get("spoof_suspect") for e in bundle.evidences)


def _liquidity_risk(bundle: EvidenceBundle, scores_cfg: Mapping[str, Any]) -> float:
    if has_name(bundle.evidences, "thin_book"):
        return PCT
    spread = first_named(bundle.evidences, "spread")
    if spread is not None and abs(spread.value) > float(scores_cfg["spread_risk_z"]):
        return PCT
    return float(scores_cfg["default_liquidity_risk"])


def _event_risk(bundle: EvidenceBundle, w: Mapping[str, Any]) -> float:
    events = w["event_values"]
    risk = 0.0
    if has_name(bundle.evidences, "headline_shock"):
        risk = max(risk, float(events["headline_shock"]))
    if has_name(bundle.evidences, "funding_window"):
        risk = max(risk, float(events["funding_window"]))
    if has_name(bundle.evidences, "weekend"):
        risk = max(risk, float(events["weekend"]))
    return risk


def _regime_alignment(direction_bias: Direction, regime: Regime, scores_cfg: Mapping[str, Any]) -> float:
    trending_up = {Regime.TRENDING_UP, Regime.BREAKOUT, Regime.RECOVERY}
    trending_down = {Regime.TRENDING_DOWN, Regime.CRASH}
    if regime is Regime.RANGING:
        return float(scores_cfg["regime_alignment_ranging"])
    agree = (
        (direction_bias is Direction.BULLISH and regime in trending_up)
        or (direction_bias is Direction.BEARISH and regime in trending_down)
    )
    if agree:
        return float(scores_cfg["regime_alignment_agree"])
    if direction_bias is Direction.NEUTRAL:
        return float(scores_cfg["regime_alignment_ranging"])
    return float(scores_cfg["regime_alignment_conflict"])


def _rr_potential(ctx: ScoreContext, scores_cfg: Mapping[str, Any], cap: float) -> float:
    if ctx.nearest_opposing_distance_atr is None:
        return 0.0
    return min(ctx.nearest_opposing_distance_atr * float(scores_cfg["rr_scale"]), cap)


__all__ = ["ScoreContext", "clamp0_100", "coin_health", "opportunity", "risk_score"]

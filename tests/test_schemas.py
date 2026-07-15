"""Contract tests for core schemas (§3, §25.1 — card P0-T2 DoD)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from aimos.core.schemas import (
    Action,
    Behavior,
    BookAggregate,
    CapacityCaps,
    DecisionRecord,
    Direction,
    EngineOpinion,
    Evidence,
    EvidenceBundle,
    ExecContext,
    Headline,
    LargePrint,
    ManagementEvent,
    MarketUnderstanding,
    OrderResult,
    OutcomeRecord,
    Position,
    Regime,
    Timeframe,
    TradePlan,
    VenueTop,
)

TS = datetime(2026, 7, 9, 14, 35, tzinfo=timezone.utc)


def _evidence() -> Evidence:
    return Evidence(
        source="volume_engine.rel_volume",
        symbol="BTC/USDT",
        timeframe=Timeframe.M5,
        timestamp=TS,
        name="volume_spike",
        value=2.7,
        direction=Direction.BULLISH,
        strength=0.55,
        reliability=0.6,
    )


def _understanding() -> MarketUnderstanding:
    return MarketUnderstanding(
        symbol="BTC",
        timestamp=TS,
        regime=Regime.TRENDING_UP,
        regime_probs={"trending_up": 0.7, "ranging": 0.3},
        behavior=Behavior.CONTINUATION,
        behavior_probs={"continuation": 0.7},
        direction_bias=Direction.BULLISH,
        p_up=0.766,
        horizon_minutes=240,
        confidence=0.428,
        coin_health=74,
        opportunity_score=71,
        risk_score=38,
        key_levels={"support": [146.8], "resistance": [153.2], "atr": 2.1},
        reasons=["BOS above 43,210 with 2.7x volume"],
    )


def _trade_plan() -> TradePlan:
    return TradePlan(
        plugin="TrendFollowing",
        symbol="BTC",
        action=Action.LONG,
        entry=150.0,
        stop_loss=145.75,
        take_profit=160.63,
        expected_rr=2.5,
        expected_hold_minutes=720,
        expected_costs_bps=19.0,
        confidence=0.30,
        score=0.61,
    )


def _all_models():
    """One instance of every model, for the round-trip sweep."""
    ev = _evidence()
    mu = _understanding()
    plan = _trade_plan()
    return [
        ev,
        EvidenceBundle(symbol="BTC", timestamp=TS, evidences=[ev]),
        EngineOpinion(engine="rule", p_up=0.81, confidence=0.66, reasons=["r"]),
        mu,
        plan,
        DecisionRecord(
            timestamp=TS,
            symbol="BTC",
            understanding=mu,
            candidates=[plan],
            chosen=plan,
            mode="paper",
        ),
        OutcomeRecord(
            decision_id="BTC-x",
            exit_time=TS,
            exit_price=160.0,
            pnl_r=1.5,
            pnl_quote=100.0,
            max_adverse_r=-0.3,
            max_favorable_r=1.7,
            exit_reason="tp",
        ),
        Headline(timestamp=TS, source="coindesk", title="ETF approved", url="http://x/1"),
        LargePrint(timestamp=TS, symbol="BTC", side=Direction.BULLISH, notional_usd=3e5, price=150.0),
        BookAggregate(
            timestamp=TS, best_bid=149.9, best_ask=150.1, spread_bps=1.3,
            bid_depth_usd=1e6, ask_depth_usd=9e5, imbalance=0.05,
        ),
        VenueTop(exchange="binance", best_bid=149.9, best_ask=150.1, mid=150.0, timestamp=TS),
        CapacityCaps(
            max_equity_pct_per_asset=25, max_pct_of_24h_volume=0.1,
            max_pct_of_book_depth=15, max_exit_slippage_bps=30, stress_exit_bps=100,
        ),
        Position(
            symbol="BTC", venue="binance", side=Action.LONG, qty=0.1, entry=150.0,
            stop=145.75, tp=160.63, opened_at=TS, plugin="TrendFollowing",
            decision_id="BTC-x", mode_tag="swing",
        ),
        ExecContext(
            equity_usdt=10000, open_positions=[], portfolio_heat_pct=0.0,
            fee_taker_bps=7.5, fee_maker_bps=2.0, slippage_entry_bps=2.0,
            slippage_exit_bps=2.0, venue="binance",
            caps=CapacityCaps(
                max_equity_pct_per_asset=25, max_pct_of_24h_volume=0.1,
                max_pct_of_book_depth=15, max_exit_slippage_bps=30, stress_exit_bps=100,
            ),
        ),
        OrderResult(ok=True, order_id="1", filled_qty=0.1, avg_price=150.0, status="filled"),
        ManagementEvent(decision_id="BTC-x", timestamp=TS, kind="breakeven", new_stop=150.0),
    ]


@pytest.mark.parametrize("model", _all_models(), ids=lambda m: type(m).__name__)
def test_json_round_trip(model):
    """Every model serializes to JSON and deserializes back identically."""
    dumped = model.model_dump_json()
    restored = type(model).model_validate_json(dumped)
    assert restored == model


def test_strength_out_of_bounds_rejected():
    with pytest.raises(ValidationError):
        Evidence(
            source="s", symbol="BTC", timeframe=Timeframe.M5, timestamp=TS,
            name="volume_spike", value=1.0, direction=Direction.BULLISH,
            strength=1.2,  # > 1 → rejected
        )


def test_negative_strength_rejected():
    with pytest.raises(ValidationError):
        Evidence(
            source="s", symbol="BTC", timeframe=Timeframe.M5, timestamp=TS,
            name="volume_spike", value=1.0, direction=Direction.BULLISH,
            strength=-0.1,
        )


def test_unknown_regime_rejected():
    with pytest.raises(ValidationError):
        MarketUnderstanding.model_validate(
            {**_understanding().model_dump(), "regime": "moon"}
        )


def test_p_up_out_of_bounds_rejected():
    with pytest.raises(ValidationError):
        mu = _understanding().model_dump()
        mu["p_up"] = 1.5
        MarketUnderstanding.model_validate(mu)


def test_extra_field_forbidden():
    with pytest.raises(ValidationError):
        Evidence(
            source="s", symbol="BTC", timeframe=Timeframe.M5, timestamp=TS,
            name="volume_spike", value=1.0, direction=Direction.BULLISH,
            strength=0.5, surprise_field=1,  # extra="forbid"
        )

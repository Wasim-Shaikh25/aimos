"""AIMOS core data contracts (§3 + §25.1).

These pydantic models are the ONLY way the three layers communicate:
    observation -> Evidence/EvidenceBundle
    intelligence -> MarketUnderstanding
    execution -> TradePlan / DecisionRecord

Hard architectural rules enforced elsewhere (import-linter, magic-number lint)
depend on these types being stable. Per standing rule 6, this file and the
evidence registry are NOT modified without explicit human approval.

All timestamps are UTC (§0 rule 6). Numeric bounds are enforced by pydantic
Field constraints so that malformed evidence/understanding cannot enter the
pipeline (e.g. strength=1.2 is rejected at construction).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aimos.core.evidence_registry import require_registered

# ---------------------------------------------------------------------------
# shared enums
# ---------------------------------------------------------------------------


class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class Timeframe(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


class Regime(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    BREAKOUT = "breakout"
    CRASH = "crash"
    RECOVERY = "recovery"


class Behavior(str, Enum):
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"
    CONTINUATION = "continuation"
    MANIPULATION = "manipulation"
    CAPITULATION = "capitulation"
    PANIC = "panic"
    EUPHORIA = "euphoria"
    UNCLEAR = "unclear"


class Action(str, Enum):
    LONG = "long"
    SHORT = "short"
    NO_TRADE = "no_trade"


# ---------------------------------------------------------------------------
# Layer 1 output
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    """Atomic unit of market observation. Layer 1's ONLY output type (§3, §5)."""

    model_config = ConfigDict(extra="forbid")

    source: str  # e.g. "volume_engine.rel_volume"
    symbol: str  # canonical base or venue symbol, e.g. "BTC" / "BTC/USDT"
    timeframe: Timeframe
    timestamp: datetime
    name: str  # e.g. "volume_spike" — must be a registered name (§25.6)
    value: float  # raw measured value
    direction: Direction  # what this evidence suggests, NOT a signal
    strength: float = Field(ge=0, le=1)  # normalized 0..1 (§5.0)
    reliability: float = Field(default=0.5, ge=0, le=1)  # prior (weights.yaml)
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _name_registered(cls, v: str) -> str:
        """Enforce evidence-name registry membership (§25.6)."""
        return require_registered(v)


class EvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    timestamp: datetime
    evidences: list[Evidence] = Field(default_factory=list)

    def by_source(self, prefix: str) -> list[Evidence]:
        return [e for e in self.evidences if e.source.startswith(prefix)]

    def by_name(self, name: str) -> list[Evidence]:
        return [e for e in self.evidences if e.name == name]


# ---------------------------------------------------------------------------
# Layer 2 intermediate + output
# ---------------------------------------------------------------------------


class EngineOpinion(BaseModel):
    """Shared intermediate: output of rule/bayes/ml engines (§6.0)."""

    model_config = ConfigDict(extra="forbid")

    engine: Literal["rule", "bayes", "ml"]
    p_up: float = Field(ge=0, le=1)  # P(price higher after horizon)
    regime_probs: dict[str, float] = Field(default_factory=dict)
    behavior_probs: dict[str, float] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)  # engine's self-assessed confidence
    reasons: list[str] = Field(default_factory=list)


class MarketUnderstanding(BaseModel):
    """Layer 2's ONLY output. Layer 3 plugins consume ONLY this (§3, §6)."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    timestamp: datetime
    regime: Regime
    regime_probs: dict[str, float] = Field(default_factory=dict)
    behavior: Behavior
    behavior_probs: dict[str, float] = Field(default_factory=dict)
    direction_bias: Direction
    p_up: float = Field(ge=0, le=1)  # fused probability price rises over horizon
    horizon_minutes: int = Field(gt=0)
    confidence: float = Field(ge=0, le=1)  # meta-confidence (§6.7)
    coin_health: float = Field(ge=0, le=100)
    opportunity_score: float = Field(ge=0, le=100)
    risk_score: float = Field(ge=0, le=100)  # higher = riskier
    key_levels: dict[str, Any] = Field(default_factory=dict)
    engine_votes: dict[str, Any] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Layer 3 output
# ---------------------------------------------------------------------------


class TradePlan(BaseModel):
    """Output of a single execution plugin (candidate) and of the evaluator (winner)."""

    model_config = ConfigDict(extra="forbid")

    plugin: str
    symbol: str
    action: Action
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    size_quote: Optional[float] = None  # position size in quote currency
    expected_rr: Optional[float] = None  # reward:risk
    expected_hold_minutes: Optional[int] = None
    expected_costs_bps: float = 0.0  # fees + slippage estimate (bps)
    confidence: float = Field(default=0.0, ge=0, le=1)
    score: float = 0.0  # evaluator score (§7.3)
    reasons: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class DecisionRecord(BaseModel):
    """One full pipeline pass — journaled for learning (§8.1)."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    symbol: str
    bundle_summary: dict[str, Any] = Field(default_factory=dict)
    understanding: MarketUnderstanding
    candidates: list[TradePlan] = Field(default_factory=list)
    chosen: TradePlan
    mode: Literal["backtest", "paper", "live"]
    decision_id: Optional[str] = None  # §25.8 decision_id, set by pipeline


class OutcomeRecord(BaseModel):
    """One closed trade — journaled for labeling/learning (§8.1)."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    exit_time: datetime
    exit_price: float
    pnl_r: float  # PnL in R multiples
    pnl_quote: float
    max_adverse_r: float  # MAE
    max_favorable_r: float  # MFE
    exit_reason: str  # "tp" | "sl" | "time" | "veto_flatten" | ...


# ---------------------------------------------------------------------------
# §25.1 — data / execution context + broker/records
# ---------------------------------------------------------------------------


class Headline(BaseModel):
    """News headline record (§4.4, §5.10)."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    source: str
    title: str
    url: str


class LargePrint(BaseModel):
    """Single large trade print detected on the public trade feed (§5.8)."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    symbol: str
    side: Direction  # BULLISH = aggressive buy, BEARISH = aggressive sell
    notional_usd: float
    price: float


class BookAggregate(BaseModel):
    """Per-snapshot order-book aggregate (§4.2)."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    best_bid: float
    best_ask: float
    spread_bps: float
    bid_depth_usd: float  # depth within 0.5% of mid
    ask_depth_usd: float
    imbalance: float = Field(ge=-1, le=1)  # (bidd - askd) / (bidd + askd)


class VenueTop(BaseModel):
    """Per-exchange top-of-book snapshot for cross-exchange work (§5.11)."""

    model_config = ConfigDict(extra="forbid")

    exchange: str
    best_bid: float
    best_ask: float
    mid: float
    timestamp: datetime


class CapacityCaps(BaseModel):
    """Resolved capacity numbers handed to the sizer (§23.10)."""

    model_config = ConfigDict(extra="forbid")

    max_equity_pct_per_asset: float
    max_pct_of_24h_volume: float
    max_pct_of_book_depth: float
    max_exit_slippage_bps: float
    stress_exit_bps: float


class Position(BaseModel):
    """An open position (§25.1)."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    venue: str
    side: Action
    qty: float
    entry: float
    stop: float
    tp: Optional[float] = None
    opened_at: datetime
    plugin: str
    decision_id: str
    mode_tag: Literal["swing", "scalp", "ignition"]


class MarketContext(BaseModel):
    """Input to ALL observation engines (§25.1).

    Holds pandas DataFrames, so arbitrary types are permitted. Windows end at
    ``now`` — engines must never see data beyond it (anti-lookahead, §9.1).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    symbol: str  # canonical base, e.g. "SOL"
    now: datetime
    candles: dict[Timeframe, Any] = Field(default_factory=dict)  # tf -> DataFrame
    orderbook_window: list[BookAggregate] = Field(default_factory=list)
    funding: Optional[Any] = None  # DataFrame(ts, rate, oi) or None
    trades_large: list[LargePrint] = Field(default_factory=list)
    headlines: list[Headline] = Field(default_factory=list)
    peers: dict[str, Any] = Field(default_factory=dict)  # base -> DataFrame
    venue_snapshot: dict[str, VenueTop] = Field(default_factory=dict)


class ExecContext(BaseModel):
    """Input to execution plugins — NO raw candles (§25.1, §7.1)."""

    model_config = ConfigDict(extra="forbid")

    equity_usdt: float
    open_positions: list[Position] = Field(default_factory=list)
    portfolio_heat_pct: float
    fee_taker_bps: float  # effective (§23.9)
    fee_maker_bps: float
    slippage_entry_bps: float  # from liquidity engine meta
    slippage_exit_bps: float
    venue: str
    caps: CapacityCaps


class OrderResult(BaseModel):
    """Result of a broker order placement (§25.1, §7.6)."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    order_id: Optional[str] = None
    filled_qty: float = 0.0
    avg_price: Optional[float] = None
    status: Literal["filled", "partial", "open", "rejected", "canceled"]
    error: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ManagementEvent(BaseModel):
    """A trade-management action, journaled + emitted to the bus (§23.1)."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    timestamp: datetime
    kind: Literal[
        "breakeven",
        "trail",
        "partial_tp",
        "thesis_exit",
        "time_stop",
        "liquidity_tighten",
        "liquidity_exit",
        "stale_cancel",
    ]
    detail: dict[str, Any] = Field(default_factory=dict)
    new_stop: Optional[float] = None
    closed_qty: Optional[float] = None


__all__ = [
    "Action",
    "Behavior",
    "BookAggregate",
    "CapacityCaps",
    "DecisionRecord",
    "Direction",
    "EngineOpinion",
    "Evidence",
    "EvidenceBundle",
    "ExecContext",
    "Headline",
    "LargePrint",
    "ManagementEvent",
    "MarketContext",
    "MarketUnderstanding",
    "OrderResult",
    "OutcomeRecord",
    "Position",
    "Regime",
    "Timeframe",
    "TradePlan",
    "VenueTop",
]

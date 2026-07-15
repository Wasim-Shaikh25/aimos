"""Frozen evidence-name registry (§25.6, card P0-T3).

Every evidence name emitted anywhere in the observation layer must be declared
here, with its declared direction semantics. This gives two guarantees:

1. The ML feature vector (§6.3) is built in registry order, so its width is
   STABLE forever — adding a name is a registry PR + a model-retrain note in
   MODELS.md (§25.6), never a silent widening.
2. ``Evidence`` construction is validated against this set (see ``schemas`` glue
   in this module): emitting an unregistered name raises.

Names are harvested from §5 (observation engines), §19 (LLM news sensor),
§21.3 (cryptofeed liquidation feed) and §23.11 (ignition). Per standing rule 6
this file is not modified without explicit human approval.

DirectionSemantics documents what a name's ``direction`` field MEANS — it is not
a hard constraint on which direction may be emitted (e.g. ``book_imbalance`` can
be bullish or bearish), but ``NEUTRAL_ONLY`` names must always emit NEUTRAL.
"""

from __future__ import annotations

from enum import Enum
from types import MappingProxyType


class DirectionSemantics(str, Enum):
    """How to read an evidence name's ``direction`` field."""

    DIRECTIONAL = "directional"  # bullish/bearish carry directional meaning
    CONTRARIAN = "contrarian"  # direction is already the contrarian read
    NEUTRAL_ONLY = "neutral_only"  # context/risk-gating; must be NEUTRAL


# name -> (source engine, direction semantics, one-line meaning).
# Order is meaningful: it fixes the ML feature-vector layout (§6.3/§25.6).
_REGISTRY: dict[str, tuple[str, DirectionSemantics, str]] = {
    # --- §5.1 Price Action ---
    "structure_trend": ("price_action", DirectionSemantics.DIRECTIONAL, "HH/HL vs LH/LL structure"),
    "bos": ("price_action", DirectionSemantics.DIRECTIONAL, "break of structure"),
    "choch": ("price_action", DirectionSemantics.DIRECTIONAL, "change of character (BOS vs trend)"),
    "fvg_nearby": ("price_action", DirectionSemantics.DIRECTIONAL, "price near unfilled fair-value gap"),
    "range_bound": ("price_action", DirectionSemantics.NEUTRAL_ONLY, "compressed range detected"),
    # --- §5.2 Volume ---
    "volume_spike": ("volume", DirectionSemantics.DIRECTIONAL, "rel_vol > threshold"),
    "volume_accel": ("volume", DirectionSemantics.DIRECTIONAL, "volume acceleration z-score"),
    "buy_pressure": ("volume", DirectionSemantics.DIRECTIONAL, "candle buy-fraction proxy"),
    "absorption": ("volume", DirectionSemantics.DIRECTIONAL, "high vol, small body — push absorbed"),
    # --- §5.3 Momentum ---
    "rsi_overbought": ("momentum", DirectionSemantics.CONTRARIAN, "RSI > overbought → bearish MR"),
    "rsi_oversold": ("momentum", DirectionSemantics.CONTRARIAN, "RSI < oversold → bullish MR"),
    "macd_cross": ("momentum", DirectionSemantics.DIRECTIONAL, "MACD histogram sign flip"),
    "momentum": ("momentum", DirectionSemantics.DIRECTIONAL, "ROC z-score"),
    "ema_slope": ("momentum", DirectionSemantics.DIRECTIONAL, "EMA(50) slope / ATR"),
    "momentum_decay": ("momentum", DirectionSemantics.DIRECTIONAL, "ROC magnitude fading vs trend"),
    # --- §5.4 Volatility (all neutral context / risk gates) ---
    "vol_compression": ("volatility", DirectionSemantics.NEUTRAL_ONLY, "ATR14/ATR100 low"),
    "vol_expansion": ("volatility", DirectionSemantics.NEUTRAL_ONLY, "ATR14/ATR100 high"),
    "vol_shock": ("volatility", DirectionSemantics.NEUTRAL_ONLY, "single-bar TR > 3x ATR"),
    # --- §5.5 Liquidity ---
    "spread": ("liquidity", DirectionSemantics.NEUTRAL_ONLY, "spread_bps z-score"),
    "thin_book": ("liquidity", DirectionSemantics.NEUTRAL_ONLY, "depth below 25th percentile"),
    "slippage_estimate": ("liquidity", DirectionSemantics.NEUTRAL_ONLY, "simulated slippage bps (meta)"),
    # --- §5.6 Order Book ---
    "book_imbalance": ("orderbook", DirectionSemantics.DIRECTIONAL, "mean book imbalance"),
    "bid_wall": ("orderbook", DirectionSemantics.DIRECTIONAL, "large resting bid (bullish)"),
    "ask_wall": ("orderbook", DirectionSemantics.DIRECTIONAL, "large resting ask (bearish)"),
    "book_absorption": ("orderbook", DirectionSemantics.DIRECTIONAL, "wall held, price bounced"),
    # --- §5.7 Funding ---
    "funding_extreme": ("funding", DirectionSemantics.CONTRARIAN, "|funding z| high → contrarian"),
    "funding_trend": ("funding", DirectionSemantics.DIRECTIONAL, "funding slope (trend confirm)"),
    "oi_divergence": ("funding", DirectionSemantics.DIRECTIONAL, "price vs OI divergence"),
    "long_short_ratio": ("funding", DirectionSemantics.CONTRARIAN, "LS ratio extreme → contrarian"),
    # --- §5.8 Whale ---
    "large_buys": ("whale", DirectionSemantics.DIRECTIONAL, "net large-print buy flow"),
    "large_sells": ("whale", DirectionSemantics.DIRECTIONAL, "net large-print sell flow"),
    "exchange_inflow": ("whale", DirectionSemantics.DIRECTIONAL, "deposits to exchange (bearish)"),
    "exchange_outflow": ("whale", DirectionSemantics.DIRECTIONAL, "withdrawals from exchange (bullish)"),
    # --- §5.9 On-chain (stub, registered) ---
    "active_addresses": ("onchain", DirectionSemantics.DIRECTIONAL, "active-address z-score"),
    "stablecoin_inflow": ("onchain", DirectionSemantics.DIRECTIONAL, "stablecoin exchange inflow"),
    # --- §5.10 Sentiment ---
    "fear_greed": ("sentiment", DirectionSemantics.CONTRARIAN, "F&G extreme → contrarian"),
    "news_tone": ("sentiment", DirectionSemantics.DIRECTIONAL, "keyword-lexicon tone"),
    "headline_shock": ("sentiment", DirectionSemantics.DIRECTIONAL, "hack/exploit/ban → risk gate"),
    # --- §5.11 Cross-Exchange ---
    "price_dislocation": ("cross_exchange", DirectionSemantics.NEUTRAL_ONLY, "max pairwise mid dev bps"),
    "lead_lag": ("cross_exchange", DirectionSemantics.DIRECTIONAL, "leading-venue move (stub P1)"),
    "venue_divergence_volume": ("cross_exchange", DirectionSemantics.NEUTRAL_ONLY, "single-venue vol spike flag"),
    # --- §5.12 Correlation ---
    "btc_beta": ("correlation", DirectionSemantics.NEUTRAL_ONLY, "rolling beta vs BTC (meta)"),
    "btc_pull": ("correlation", DirectionSemantics.DIRECTIONAL, "large BTC move drags alt"),
    "decoupling": ("correlation", DirectionSemantics.NEUTRAL_ONLY, "corr with BTC collapsed"),
    # --- §5.13 Time (all neutral context) ---
    "session": ("time", DirectionSemantics.NEUTRAL_ONLY, "asia/europe/us session (meta)"),
    "weekend": ("time", DirectionSemantics.NEUTRAL_ONLY, "weekend flag (+risk)"),
    "funding_window": ("time", DirectionSemantics.NEUTRAL_ONLY, "near funding settlement"),
    # --- §19 LLM news sensor (event-typed) ---
    "news_hack": ("sentiment_llm", DirectionSemantics.DIRECTIONAL, "LLM-classified hack event"),
    "news_regulatory": ("sentiment_llm", DirectionSemantics.DIRECTIONAL, "LLM-classified regulatory event"),
    "news_etf_flows": ("sentiment_llm", DirectionSemantics.DIRECTIONAL, "LLM-classified ETF flows"),
    "news_listing": ("sentiment_llm", DirectionSemantics.DIRECTIONAL, "LLM-classified listing"),
    "news_delisting": ("sentiment_llm", DirectionSemantics.DIRECTIONAL, "LLM-classified delisting"),
    "news_partnership": ("sentiment_llm", DirectionSemantics.DIRECTIONAL, "LLM-classified partnership"),
    "news_macro": ("sentiment_llm", DirectionSemantics.DIRECTIONAL, "LLM-classified macro event"),
    "news_exploit": ("sentiment_llm", DirectionSemantics.DIRECTIONAL, "LLM-classified exploit"),
    "news_bankruptcy": ("sentiment_llm", DirectionSemantics.DIRECTIONAL, "LLM-classified bankruptcy"),
    "news_upgrade": ("sentiment_llm", DirectionSemantics.DIRECTIONAL, "LLM-classified upgrade"),
    "news_rumor": ("sentiment_llm", DirectionSemantics.DIRECTIONAL, "LLM-classified rumor"),
    "news_other": ("sentiment_llm", DirectionSemantics.DIRECTIONAL, "LLM-classified other event"),
    # --- §21.3 cryptofeed liquidations ---
    "liquidation_cascade": ("streams", DirectionSemantics.CONTRARIAN, "liquidation notional z → fade"),
    # --- §23.11 Ignition ---
    "ignition": ("ignition", DirectionSemantics.DIRECTIONAL, "violent repricing detected (may be gated NEUTRAL)"),
    # --- §20.1 Factor engine (dynamic ids share this family prefix) ---
    # Individual factor evidences use name=f"factor_{alpha_id}"; the registry
    # records the family here and membership is checked by prefix (see below).
    "factor": ("factor_engine", DirectionSemantics.DIRECTIONAL, "cross-sectional factor z (family prefix)"),
}

# Names whose concrete evidence names are generated with a suffix (e.g. the
# factor engine emits ``factor_<alpha_id>``). Membership is by prefix match.
_FAMILY_PREFIXES: frozenset[str] = frozenset({"factor"})

REGISTRY: MappingProxyType[str, tuple[str, DirectionSemantics, str]] = MappingProxyType(_REGISTRY)
EVIDENCE_NAMES: tuple[str, ...] = tuple(_REGISTRY.keys())


class UnregisteredEvidenceName(ValueError):
    """Raised when an evidence name is not present in the frozen registry."""


def is_registered(name: str) -> bool:
    """True if ``name`` is a declared evidence name or a family member."""
    if name in _REGISTRY:
        return True
    return any(
        name.startswith(prefix + "_") for prefix in _FAMILY_PREFIXES
    )


def require_registered(name: str) -> str:
    """Return ``name`` if registered, else raise ``UnregisteredEvidenceName``."""
    if not is_registered(name):
        raise UnregisteredEvidenceName(
            f"evidence name {name!r} is not in the frozen registry "
            f"({len(EVIDENCE_NAMES)} names). Add it via a registry PR (§25.6)."
        )
    return name


def semantics(name: str) -> DirectionSemantics:
    """Direction semantics for a registered name (family members inherit)."""
    if name in _REGISTRY:
        return _REGISTRY[name][1]
    for prefix in _FAMILY_PREFIXES:
        if name.startswith(prefix + "_"):
            return _REGISTRY[prefix][1]
    raise UnregisteredEvidenceName(name)


def feature_index() -> dict[str, int]:
    """Stable name -> index map for the ML feature vector (§6.3, §25.6)."""
    return {name: i for i, name in enumerate(EVIDENCE_NAMES)}


__all__ = [
    "DirectionSemantics",
    "EVIDENCE_NAMES",
    "REGISTRY",
    "UnregisteredEvidenceName",
    "feature_index",
    "is_registered",
    "require_registered",
    "semantics",
]

"""Typed configuration loader — zero-hardcoding core (§12, §23.12, card P0-T4).

All tunable values live in ``config/*.yaml`` and are loaded here into one
validated ``Params`` tree. Guarantees:

* **Validation at startup** — range checks via pydantic ``Field`` constraints;
  a bad range (e.g. ``base_risk_pct = 5``) fails the load, not silently.
* **Env overrides** — ``AIMOS__EXECUTION__BASE_RISK_PCT=0.25`` maps onto
  ``params.execution.base_risk_pct`` (double-underscore nesting, §23.12).
* **Hot-reload whitelist** — only a safe subset (thresholds, not structural
  cadences) may change at runtime; every applied change is journaled.
* **Change journaling hook** — a settable callback receives (path, old, new);
  the default logs via structlog (stub wiring to the real journal comes later).

``default.yaml``'s top-level sections become top-level ``Params`` fields; every
other config file becomes one field named by its stem; ``config/plugins/*.yaml``
become the ``plugins`` mapping.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Optional

import structlog
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

log = structlog.get_logger(__name__)

ENV_PREFIX = "AIMOS__"
CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

# Paths (dotted, from Params root) allowed to change on hot-reload (§23.12:
# "thresholds yes, structural cadences no").
HOT_RELOAD_WHITELIST: frozenset[str] = frozenset(
    {
        "intelligence.min_confidence",
        "intelligence.direction_bias.bull",
        "intelligence.direction_bias.bear",
        "intelligence.bayes_likelihood_lift",
        "execution.min_trade_score",
        "execution.no_trade_baseline",
        "execution.base_risk_pct",
        "execution.max_cost_fraction",
        "execution.risk_score_veto",
        "tiers.promote",
        "tiers.demote",
    }
)

# Change-journaling hook (stub). Real wiring records old→new to the journal
# (§23.12). Default implementation logs.
ChangeJournal = Callable[[str, Any, Any], None]


def _default_change_journal(path: str, old: Any, new: Any) -> None:
    log.info("config_change", path=path, old=old, new=new)


_change_journal: ChangeJournal = _default_change_journal


def set_change_journal(fn: ChangeJournal) -> None:
    """Install the config-change journaling hook (§23.12)."""
    global _change_journal
    _change_journal = fn


# ---------------------------------------------------------------------------
# Typed sub-models (the decision-path sections get real range validation).
# Sections not yet consumed are modelled permissively (extra="allow") so the
# full initial config loads today and gets tightened as later phases land.
# ---------------------------------------------------------------------------


class _Loose(BaseModel):
    """Permissive base for config not yet range-validated."""

    model_config = ConfigDict(extra="allow")


class DirectionBias(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bull: float = Field(ge=0.5, le=1.0)
    bear: float = Field(ge=0.0, le=0.5)


class FusionWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: float = Field(ge=0, le=1)
    bayes: float = Field(ge=0, le=1)
    ml: float = Field(ge=0, le=1)


class IntelligenceConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    direction_bias: DirectionBias
    min_confidence: float = Field(ge=0, le=1)
    bayes_likelihood_lift: float = Field(ge=0, le=1)
    correlation_guard_keep: int = Field(ge=1, le=10)
    fusion_weights: FusionWeights


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    min_trade_score: float = Field(ge=0, le=1)
    no_trade_baseline: float = Field(ge=0, le=1)
    base_risk_pct: float = Field(gt=0, le=1.0)  # §23.12 risk_pct ∈ (0, 1]
    max_portfolio_heat_pct: float = Field(gt=0, le=10)
    max_positions: int = Field(ge=1, le=50)
    max_per_symbol: int = Field(ge=1, le=10)
    daily_stop_pct: float = Field(gt=0, le=100)
    risk_score_veto: float = Field(ge=0, le=100)
    ev_norm_cap_r: float = Field(gt=0)
    max_cost_fraction: float = Field(ge=0, le=1)


class TiersConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    t1_max: int = Field(ge=1, le=24)
    t2_max: int = Field(ge=1, le=200)
    promote: float = Field(ge=0, le=100)
    demote: float = Field(ge=0, le=100)
    demote_scans: int = Field(ge=1, le=20)

    @model_validator(mode="after")
    def _promote_above_demote(self) -> "TiersConfig":
        if self.promote <= self.demote:
            raise ValueError("tiers.promote must exceed tiers.demote (hysteresis)")
        return self


class CostsConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    taker_bps: float = Field(ge=0, le=1000)
    maker_bps: float = Field(ge=0, le=1000)
    slip_base_bps: float = Field(ge=0, le=1000)
    slip_k: float = Field(ge=0)


class Params(BaseModel):
    """The full validated configuration tree."""

    model_config = ConfigDict(extra="allow")

    # --- from default.yaml (top-level sections) ---
    dev_symbols: list[str]
    base_timeframe: str
    analysis_timeframes: list[str]
    horizon_minutes: int = Field(ge=5, le=10080)
    exchanges: dict[str, Any]
    tiers: TiersConfig
    intelligence: IntelligenceConfig
    execution: ExecutionConfig
    runtime: _Loose
    ratelimit: _Loose  # §23.2
    data: _Loose  # §4
    data_quality: _Loose  # §23.3
    mode: str = Field(pattern="^(paper|live)$")

    # --- from the other config files (one field per file stem) ---
    weights: _Loose
    universe: _Loose
    observation: _Loose  # §5 engine thresholds
    costs: CostsConfig
    capacity: _Loose
    ignition: _Loose
    scalp: _Loose
    protections: _Loose
    behavior_likelihoods: _Loose
    factors_active: _Loose
    mandate: _Loose
    scenarios: _Loose
    counterparty: _Loose
    optimize_space: _Loose
    trade_manager: _Loose
    plugins: dict[str, _Loose] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def _build_raw(config_dir: Path) -> dict[str, Any]:
    """Assemble the raw (pre-validation) config dict from the file inventory."""
    default = _read_yaml(config_dir / "default.yaml")
    # `universe:` in default.yaml is just a ref pointer; the real content lives
    # in universe.yaml. Drop the pointer to avoid a field collision.
    default.pop("universe", None)

    raw: dict[str, Any] = dict(default)

    single_files = [
        "weights",
        "universe",
        "observation",
        "costs",
        "capacity",
        "ignition",
        "scalp",
        "protections",
        "behavior_likelihoods",
        "factors_active",
        "mandate",
        "scenarios",
        "counterparty",
        "optimize_space",
        "trade_manager",
    ]
    for stem in single_files:
        raw[stem] = _read_yaml(config_dir / f"{stem}.yaml")

    plugins_dir = config_dir / "plugins"
    plugins: dict[str, Any] = {}
    if plugins_dir.is_dir():
        for pf in sorted(plugins_dir.glob("*.yaml")):
            plugins[pf.stem] = _read_yaml(pf)
    raw["plugins"] = plugins
    return raw


def _coerce_env_value(text: str) -> Any:
    """Parse an env override string into a typed scalar/list via YAML rules."""
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return text


def _apply_env_overrides(raw: dict[str, Any], environ: dict[str, str]) -> list[str]:
    """Apply ``AIMOS__A__B__C=value`` overrides in place. Returns changed paths."""
    changed: list[str] = []
    for key, val in environ.items():
        if not key.startswith(ENV_PREFIX):
            continue
        path = key[len(ENV_PREFIX) :].lower().split("__")
        node: dict[str, Any] = raw
        ok = True
        for part in path[:-1]:
            nxt = node.get(part)
            if not isinstance(nxt, dict):
                ok = False
                break
            node = nxt
        if not ok:
            log.warning("env_override_unknown_path", env=key)
            continue
        node[path[-1]] = _coerce_env_value(val)
        changed.append(".".join(path))
    return changed


def load_params(
    config_dir: Path | str | None = None,
    environ: Optional[dict[str, str]] = None,
) -> Params:
    """Load, override, and validate the full config tree.

    Raises ``pydantic.ValidationError`` if any value is out of range (startup
    fails loudly rather than trading on a bad config).
    """
    cdir = Path(config_dir) if config_dir else CONFIG_DIR
    raw = _build_raw(cdir)
    env = environ if environ is not None else dict(os.environ)
    _apply_env_overrides(raw, env)
    return Params.model_validate(raw)


# ---------------------------------------------------------------------------
# hot reload
# ---------------------------------------------------------------------------


def _get_path(model: BaseModel, dotted: str) -> Any:
    node: Any = model
    for part in dotted.split("."):
        node = getattr(node, part) if isinstance(node, BaseModel) else node[part]
    return node


def _set_path(model: BaseModel, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node: Any = model
    for part in parts[:-1]:
        node = getattr(node, part) if isinstance(node, BaseModel) else node[part]
    last = parts[-1]
    if isinstance(node, BaseModel):
        setattr(node, last, value)
    else:
        node[last] = value


def hot_reload(
    current: Params,
    config_dir: Path | str | None = None,
) -> list[str]:
    """Re-read config and apply ONLY whitelisted changes to ``current``.

    Structural (non-whitelisted) changes are ignored — they require a restart.
    Each applied change is journaled via the change hook. Returns applied paths.
    """
    fresh = load_params(config_dir)
    applied: list[str] = []
    for path in sorted(HOT_RELOAD_WHITELIST):
        try:
            new = _get_path(fresh, path)
            old = _get_path(current, path)
        except (AttributeError, KeyError, TypeError):
            continue
        if new != old:
            _set_path(current, path, new)
            _change_journal(path, old, new)
            applied.append(path)
    return applied


__all__ = [
    "CONFIG_DIR",
    "HOT_RELOAD_WHITELIST",
    "Params",
    "hot_reload",
    "load_params",
    "set_change_journal",
]

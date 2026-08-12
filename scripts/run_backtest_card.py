#!/usr/bin/env python3
"""Generate per-strategy 12-month costed walk-forward backtest run cards (T-003).

Usage:
    python scripts/run_backtest_card.py
    python scripts/run_backtest_card.py --timeframe 1h --months 12 --exchange binance
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

# Allow running from repo root without installing.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aimos.backtest.engine import BacktestEngine  # noqa: E402
from aimos.backtest.metrics import compute_metrics, max_drawdown  # noqa: E402
from aimos.backtest.validation import ValidationResult, make_run_card, validate_returns  # noqa: E402
from aimos.core.config import load_params  # noqa: E402
from aimos.data.binance_symbols import all_binance_usdt_spot_symbols  # noqa: E402
from aimos.data.candles import CandleStore  # noqa: E402
from aimos.data.universe_source import build_universe  # noqa: E402


_DEFAULT_RUNCARDS = ROOT / "specs" / "runcards"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _tier1_symbols(params, exchange: str, t1_max_override: int | None) -> list[str]:
    """Return Tier-1 symbols from the offline seed universe."""
    ucfg = params.universe.model_dump()
    t1_max = t1_max_override or int(ucfg.get("tiers", {}).get("t1_max", 12))
    universe = build_universe(exchange, ucfg, live_data=False, max_symbols=t1_max)
    return universe.symbols


def _download(exchange: str, symbols: list[str], timeframe: str, months: int, data_dir: str) -> int:
    symbols_arg = ",".join(symbols)
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "download_history.py"),
        "--exchange", exchange,
        "--symbol", symbols_arg,
        "--timeframe", timeframe,
        "--months", str(months),
        "--data-dir", data_dir,
    ]
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, text=True, check=False)
    return result.returncode


def _integrity(data_dir: str) -> int:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "dataset_integrity.py"), data_dir],
        cwd=ROOT,
        text=True,
        check=False,
    )
    return result.returncode


def _strategy_metrics(trades: list[dict], starting_equity: float, n_decisions: int) -> dict[str, Any]:
    """Compute per-strategy summary from closed trade dicts."""
    n = len(trades)
    if n == 0:
        return {
            "trades": 0, "win_rate": 0.0, "total_pnl_usd": 0.0, "avg_pnl_r": 0.0,
            "median_pnl_r": 0.0, "sharpe": 0.0, "max_drawdown": 0.0,
            "profit_factor": 0.0, "exposure_pct": 0.0, "avg_mae_r": 0.0,
            "avg_mfe_r": 0.0, "no_trade_rate": 1.0,
        }
    pnls = [t["pnl_usd"] for t in trades]
    rs = [t["pnl_r"] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gross_win = sum(wins) if wins else 0.0
    gross_loss = -sum(losses) if losses else 0.0
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")

    equity = [starting_equity]
    for p in pnls:
        equity.append(equity[-1] + p)
    eq_arr = pd.Series(equity)
    rets = eq_arr.pct_change().dropna().values
    sharpe = 0.0
    if len(rets) > 1 and rets.std(ddof=1) > 0:
        sharpe = float(rets.mean() / rets.std(ddof=1) * (365.0 ** 0.5))

    m = compute_metrics(
        equity, rs, n_decisions=n_decisions, n_no_trade=0, days=max((len(equity) - 1) / 365.0, 1.0)
    )
    return {
        "trades": n,
        "win_rate": float(len(wins) / n) if n else 0.0,
        "total_pnl_usd": round(sum(pnls), 4),
        "avg_pnl_r": round(float(pd.Series(rs).mean()), 4),
        "median_pnl_r": round(float(pd.Series(rs).median()), 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_drawdown(eq_arr.values), 4),
        "profit_factor": round(profit_factor, 4),
        "exposure_pct": round(m.exposure_pct, 4),
        "avg_mae_r": round(float(pd.Series([t["max_adverse_r"] for t in trades]).mean()), 4),
        "avg_mfe_r": round(float(pd.Series([t["max_favorable_r"] for t in trades]).mean()), 4),
        "no_trade_rate": 0.0,
    }


def _verdict(metrics: dict, validation: ValidationResult) -> str:
    n = metrics["trades"]
    if n < 30:
        return "insufficient sample"
    if validation.passes_promotion_gate and metrics["total_pnl_usd"] > 0:
        return "edge"
    return "no edge"


def _run_symbol(
    params: Any,
    symbol: str,
    candles: pd.DataFrame,
    btc_candles: pd.DataFrame | None,
    exchange: str,
    starting_equity: float,
    engine_profile: str,
    seed: int,
    runcards_dir: Path,
    git_sha: str,
    params_dict: dict,
) -> dict[str, Any]:
    """Run the backtest for one symbol and write per-strategy run cards."""
    peers = None
    if btc_candles is not None and not btc_candles.empty:
        peers = {"BTC": btc_candles}

    engine = BacktestEngine(
        params,
        symbol,
        starting_equity=starting_equity,
        engine_profile=engine_profile,
        journal_path=":memory:",
    )
    result = engine.run(candles, peers=peers)

    # Group closed trades by strategy plugin.
    all_trades = [t for t in result.broker.trade_history() if t["status"] == "closed"]
    by_strategy: dict[str, list[dict]] = {}
    for t in all_trades:
        by_strategy.setdefault(t["strategy"], []).append(t)

    # Produce a run card for every enabled strategy (except RiskOff), even if it
    # never traded — an honest "insufficient sample / no edge" verdict is data.
    plugin_names = {p.name for p in engine.execution.plugins if p.name != "RiskOff"}
    run_ids: list[str] = []
    for strategy in sorted(plugin_names):
        trades = by_strategy.get(strategy, [])
        metrics = _strategy_metrics(trades, starting_equity, result.n_decisions)
        returns = [t["pnl_r"] for t in trades]
        validation = validate_returns(returns, seed=seed)
        metrics["verdict"] = _verdict(metrics, validation)
        metrics["symbol"] = symbol
        metrics["strategy"] = strategy
        metrics["exchange"] = exchange
        metrics["engine_profile"] = engine_profile

        equity_curve = [starting_equity]
        for t in trades:
            equity_curve.append(equity_curve[-1] + t["pnl_usd"])

        run_id = f"t003-{strategy}-{symbol.replace('/', '')}-{engine_profile}-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
        runcard = make_run_card(
            run_id=run_id,
            git_sha=git_sha,
            params_dict=params_dict,
            equity_curve=equity_curve,
            metrics=metrics,
            validation=validation,
            seed=seed,
            engine_profile=engine_profile,
            universe_snapshot_id=f"{exchange}-tier1-{len(all_trades)}",
        )
        path = runcards_dir / f"{run_id}.yaml"
        path.write_text(runcard.to_yaml(), encoding="utf-8")
        run_ids.append(run_id)

    return {
        "symbol": symbol,
        "trades": len(all_trades),
        "decisions": result.n_decisions,
        "final_equity": result.broker.equity(),
        "run_ids": run_ids,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run 12-month costed walk-forward backtest and emit run cards.")
    ap.add_argument("--exchange", default="binance", help="exchange/data source")
    ap.add_argument("--timeframe", default="1h", help="candle interval")
    ap.add_argument("--months", type=int, default=12, help="months of history")
    ap.add_argument("--data-dir", default="data", help="CandleStore root")
    ap.add_argument("--runcards-dir", default=str(_DEFAULT_RUNCARDS), help="output directory")
    ap.add_argument("--symbols", default="", help="comma-separated symbols; default = Tier-1 universe")
    ap.add_argument("--all", action="store_true", help="use all currently trading non-stable Binance USDT spot pairs")
    ap.add_argument("--top-n", type=int, default=None, help="when --all, backtest only the top-N by 24h quote volume")
    ap.add_argument("--include-stable", action="store_true", help="when --all, include USDT pairs where the base is a stablecoin")
    ap.add_argument("--t1-max", type=int, default=None, help="max Tier-1 symbols to backtest")
    ap.add_argument("--starting-equity", type=float, default=10_000.0)
    ap.add_argument("--engine-profile", default="no_book")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--download-only", action="store_true", help="download/verify data and exit")
    ap.add_argument("--skip-download", action="store_true", help="use existing parquet if present")
    args = ap.parse_args(argv)

    params = load_params()
    runcards_dir = Path(args.runcards_dir)
    runcards_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path(args.data_dir)

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    elif args.all:
        symbols = asyncio.run(
            all_binance_usdt_spot_symbols(args.top_n, include_stable=args.include_stable)
        )
    else:
        symbols = _tier1_symbols(params, args.exchange, args.t1_max)

    if not symbols:
        print("No symbols to backtest.")
        return 2

    print("Symbols:", symbols)

    if not args.skip_download:
        # Always have BTC as a peer for the correlation engine.
        download_symbols = list(symbols)
        if "BTC/USDT" not in download_symbols:
            download_symbols.append("BTC/USDT")

        rc = _download(args.exchange, download_symbols, args.timeframe, args.months, str(data_dir))
        if rc != 0:
            print(f"Download failed (exit {rc}); continuing if any parquet files exist.")

    if _integrity(str(data_dir)) != 0:
        print("Dataset integrity check failed.")
        return 1

    if args.download_only:
        print("Download and integrity OK.")
        return 0

    store = CandleStore(data_dir)
    btc_candles = store.read(args.exchange, "BTC/USDT", args.timeframe)

    git_sha = _git_sha()
    params_dict = json.loads(params.model_dump_json())

    summaries: list[dict] = []
    for symbol in symbols:
        candles = store.read(args.exchange, symbol, args.timeframe)
        if candles.empty:
            print(f"{symbol}: no data, skipping")
            continue
        print(f"{symbol}: running backtest ({len(candles)} bars)")
        summary = _run_symbol(
            params, symbol, candles,
            btc_candles if symbol != "BTC/USDT" else candles,
            args.exchange, args.starting_equity, args.engine_profile,
            args.seed, runcards_dir, git_sha, params_dict,
        )
        summaries.append(summary)
        print(f"  -> {summary['trades']} trades, final equity ${summary['final_equity']:.2f}")

    print("\nRun cards written:")
    for s in summaries:
        for rid in s["run_ids"]:
            print(f"  {runcards_dir / f'{rid}.yaml'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""Train the ML model on OLDER data by replaying it as paper trades (§6.3, §8.3).

This is the "train in paper trading on historical Binance data" entrypoint. It
replays old candles through the exact production pipeline, labels every decision
(triple-barrier), trains a walk-forward-validated logistic model, and reports
whether it clears the promotion gate — then saves the artifact in SHADOW (it does
NOT touch live decisions; you enable it deliberately afterward).

    # 1) turn the feature on (disabled by default — the enable/disable switch):
    export AIMOS__LEARNING__HISTORY__ENABLED=true
    # 2) train on data you provide (pick ONE source):
    python -m scripts.train_from_history --synthetic --symbols BTC/USDT,ETH/USDT   # offline demo
    python -m scripts.train_from_history --csv 'data/BTCUSDT-1h-*.csv' --symbol BTC/USDT
    python -m scripts.train_from_history --parquet --exchange binance --symbol BTC/USDT --timeframe 1h

Binance publishes free historical klines at https://data.binance.vision/ (e.g.
data/spot/monthly/klines/BTCUSDT/1h/…): download, unzip, point --csv at them.

The model is DISABLED (fusion weight 0, shadow) until you promote it — the script
prints the exact one-line change to enable it, and only if the gate passes.
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_BINANCE_KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume",
                       "close_time", "qav", "trades", "tbav", "tqav", "ignore"]


def _load_csv(pattern: str) -> pd.DataFrame:
    """Load + concat Binance-vision kline CSVs (headerless, 12 cols) → OHLCV df."""
    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"no CSVs matched {pattern!r}")
    frames = []
    for f in files:
        raw = pd.read_csv(f, header=None, names=_BINANCE_KLINE_COLS)
        raw.index = pd.to_datetime(raw["open_time"], unit="ms", utc=True)
        frames.append(raw[["open", "high", "low", "close", "volume"]].astype(float))
    df = pd.concat(frames).sort_index()
    return df[~df.index.duplicated(keep="first")]


def _load_parquet(exchange: str, symbol: str, timeframe: str) -> pd.DataFrame:
    from aimos.data.candles import CandleStore
    df = CandleStore("data").read(exchange, symbol, timeframe)
    if df.empty:
        raise SystemExit(f"no parquet for {exchange}/{symbol}/{timeframe} under data/ "
                         f"(fetch first with scripts/candles or ccxt)")
    return df


def _load_synthetic(symbol: str, bars: int) -> pd.DataFrame:
    from aimos.data.live_source import SyntheticSource
    return SyntheticSource(seed=abs(hash(symbol)) % 997).fetch(symbol, "1h", bars)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Train the ML model on historical data (shadow).")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--synthetic", action="store_true", help="offline synthetic candles (demo/test)")
    src.add_argument("--csv", help="glob of Binance-vision kline CSVs")
    src.add_argument("--parquet", action="store_true", help="read from the CandleStore under data/")
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--symbols", help="comma list (overrides --symbol) — pool multiple assets")
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--bars", type=int, default=4000, help="synthetic bar count per symbol")
    ap.add_argument("--out", default="", help="model artifact path (default: intelligence.ml_model_path or state/ml_model.json)")
    args = ap.parse_args(argv)

    from aimos.core.config import load_params
    from aimos.learning.dataset import build_training_set
    from aimos.learning.train import PromotionChecklist, train_model

    params = load_params()
    hist = params.model_dump().get("learning", {}).get("history", {}) or {}
    if not hist.get("enabled", False):
        print("history training is DISABLED. Enable it with "
              "AIMOS__LEARNING__HISTORY__ENABLED=true (or learning.history.enabled: true).")
        return 3

    horizon = int(hist.get("horizon_bars", 24))
    warmup = int(hist.get("warmup", 200))
    n_folds = int(hist.get("n_folds", 3))
    ml_cfg = params.intelligence.model_dump()  # fusion_weights, coverage, etc.
    lm = params.model_dump().get("learning", {}).get("ml", {})
    min_samples = int(lm.get("min_labeled_samples", 2000))
    auc_min = float(lm.get("val_auc_min", 0.55))
    shadow_weeks_req = int(lm.get("shadow_weeks", 2))

    symbols = [s.strip() for s in (args.symbols or args.symbol).split(",") if s.strip()]
    Xs: list[np.ndarray] = []
    ys: list[int] = []
    ts: list = []
    total_scanned = 0
    for sym in symbols:
        if args.synthetic:
            candles = _load_synthetic(sym, args.bars)
        elif args.csv:
            candles = _load_csv(args.csv)
        else:
            candles = _load_parquet(args.exchange, sym, args.timeframe)
        ds = build_training_set(params, sym, candles, horizon_bars=horizon, warmup=warmup)
        total_scanned += ds.n_scanned
        if ds.n_labeled:
            Xs.append(ds.X)
            ys.extend(ds.y)
            ts.extend(ds.timestamps)
        print(f"  {sym}: {len(candles)} bars → scanned {ds.n_scanned}, labeled {ds.n_labeled}")

    n = len(ys)
    print(f"\ntotal labeled samples: {n} (scanned {total_scanned}); "
          f"class balance up={sum(ys)}, down={n - sum(ys)}")
    if n < min_samples:
        print(f"❌ below min_labeled_samples ({n} < {min_samples}) — gather more history "
              f"before training (§8.3). Model NOT trained.")
        return 4
    if len(set(ys)) < 2:
        print("❌ only one class present — cannot train a classifier.")
        return 4

    X = np.vstack(Xs)
    model = train_model(X, ys, ts, n_folds=n_folds)
    checklist = PromotionChecklist(val_auc=model.val_auc, brier_improves=False,
                                   shadow_weeks_held=0)
    passes_auc = model.val_auc > auc_min

    out = args.out or ml_cfg.get("ml_model_path") or "state/ml_model.json"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    model.save(out)

    print("\n" + "=" * 64)
    print(f"walk-forward val AUC: {model.val_auc:.4f}  (gate: > {auc_min})  "
          f"→ {'PASS' if passes_auc else 'FAIL'}")
    print(f"model saved: {out}  (features: {model.n_features})")
    print("\nML is currently DISABLED (fusion weight 0 — shadow). To ENABLE it, set:")
    print(f"   AIMOS__INTELLIGENCE__ML_MODEL_PATH={out}")
    if passes_auc:
        print("   AIMOS__INTELLIGENCE__FUSION_WEIGHTS__ML=0.15   # start small; watch it in shadow first")
        print(f"\n⚠️  AUC passed, but full promotion also needs {shadow_weeks_req} weeks of shadow "
              "operation + a Brier improvement (§8.3) before you trust the weight.")
    else:
        print("   (leave the weight at 0 — the model did not clear the AUC gate; retrain with more/"
              "better data before enabling.)")
    _ = checklist  # reported above; kept explicit for auditability
    return 0 if passes_auc else 1


if __name__ == "__main__":
    sys.exit(main())

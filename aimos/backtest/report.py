"""Minimal self-contained HTML backtest report (§9.3, §20.2, card P4-T8)."""

from __future__ import annotations

from aimos.backtest.metrics import Metrics
from aimos.backtest.validation import RunCard


def render_report(card: RunCard, metrics: Metrics) -> str:
    rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in metrics.to_dict().items())
    val = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in card.validation.items())
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>AIMOS Backtest {card.run_id}</title></head><body>
<h1>AIMOS Backtest — {card.run_id}</h1>
<p>git {card.git_sha} · config {card.config_hash} · data {card.data_hash} · profile {card.engine_profile}</p>
<h2>Metrics</h2><table border=1>{rows}</table>
<h2>Validation (§20.2)</h2><table border=1>{val}</table>
</body></html>"""


__all__ = ["render_report"]

import React from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Tile, Spark, Table, Empty } from '../components/ui'

// Performance (§5.6): realized PnL, win rate, drawdown, per-strategy & per-venue.
export default function Performance() {
  const { data: eq } = usePoll(api.equity, 4000)
  const { data: p } = usePoll(api.performance, 4000)
  const curve = eq?.equity || []
  const byStrat = p?.by_strategy || {}
  const byVenue = p?.by_venue || {}
  return <div className="page"><h1>Performance</h1>
    <div className="tiles">
      <Tile k="Closed trades" v={p?.closed_trades ?? '—'} />
      <Tile k="Win rate" v={p ? (p.win_rate * 100).toFixed(0) + '%' : '—'} />
      <Tile k="Realized PnL" v={p ? `$${p.realized_pnl_usd.toFixed(2)}` : '—'} />
      <Tile k="Arb trades" v={p?.arb_trades ?? '—'} />
      <Tile k="Arb PnL" v={p ? `$${p.arb_pnl_usd.toFixed(2)}` : '—'} />
      <Tile k="Max drawdown" v={p ? p.max_drawdown_pct.toFixed(2) + '%' : '—'} />
    </div>
    <h2>Equity curve</h2>
    {curve.length > 1 ? <Spark points={curve} /> : <Empty what="equity points" />}
    <h2>By strategy</h2>
    {Object.keys(byStrat).length ? <Table cols={['Strategy', 'Trades', 'PnL (USDT)']}
      rows={Object.entries(byStrat).map(([k, v]) => [k, v.trades, `$${v.pnl_usd.toFixed(2)}`])} />
      : <p className="muted">no closed trades yet.</p>}
    <h2>By venue</h2>
    {Object.keys(byVenue).length ? <Table cols={['Venue(s)', 'Trades', 'PnL (USDT)']}
      rows={Object.entries(byVenue).map(([k, v]) => [k, v.trades, `$${v.pnl_usd.toFixed(2)}`])} />
      : <p className="muted">no closed trades yet.</p>}
  </div>
}

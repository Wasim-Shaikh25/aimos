import React from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Badge, Table, Empty } from '../components/ui'

// Trade History (§5.5): directional trades + cross-venue arb legs (buy→sell).
export default function Trades() {
  const { data } = usePoll(api.trades, 4000)
  const trades = data?.trades || []
  return <div className="page"><h1>Trade History <span className="muted" style={{ fontSize: 14 }}>({trades.length}, {data?.n_arb || 0} arb)</span></h1>
    {trades.length === 0 ? <Empty what="trades" /> :
      <div style={{ overflowX: 'auto' }}><Table
        cols={['Time', 'Kind', 'Asset', 'Strategy', 'Venue(s)', 'Side', 'Qty', 'Entry', 'Exit', 'PnL (USDT)', 'Status']}
        rows={trades.map(t => [
          <span className="mono">{(t.closed_at || t.opened_at || '').slice(0, 19)}</span>,
          <Badge dir={t.kind === 'arb' ? 'up' : 'flat'}>{t.kind}</Badge>,
          t.symbol, t.strategy, t.venue, t.side,
          t.qty != null ? Number(t.qty).toFixed(4) : '—',
          t.entry != null ? Number(t.entry).toFixed(2) : '—',
          t.exit != null ? Number(t.exit).toFixed(2) : '—',
          <span style={{ color: t.pnl_usd > 0 ? 'var(--green)' : t.pnl_usd < 0 ? 'var(--red)' : 'var(--muted)' }}>
            {t.pnl_usd > 0 ? '+' : ''}{Number(t.pnl_usd).toFixed(2)}</span>,
          <Badge dir={t.status === 'open' ? 'flat' : (t.pnl_usd >= 0 ? 'up' : 'down')}>{t.result}</Badge>,
        ])} /></div>}
  </div>
}

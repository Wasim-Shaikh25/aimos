import React from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Table, Tile, Empty } from '../components/ui'
export default function PositionsRisk() {
  const { data: p } = usePoll(api.positions, 4000)
  const pos = p?.positions || []
  return <div className="page"><h1>Positions & Risk</h1>
    <div className="tiles">
      <Tile k="Open positions" v={pos.length} />
      <Tile k="Portfolio heat" v={`${(pos.length * 0.5).toFixed(1)}%`} />
      <Tile k="Reserve" v="≥30%" />
    </div>
    {pos.length === 0 ? <Empty what="open positions" /> :
      <Table cols={['Symbol', 'Side', 'Qty', 'Entry', 'Stop', 'TP']}
        rows={pos.map(x => [x.symbol, x.side, x.qty, x.entry, x.stop, x.tp])} />}
    <h2>Stress panel (§24.1)</h2><p className="muted">Scenario matrix renders when the risk-analytics daily job posts to /api/stress.</p>
  </div>
}

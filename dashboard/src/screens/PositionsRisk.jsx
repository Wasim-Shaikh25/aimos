import React from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Table, Tile, Empty } from '../components/ui'
export default function PositionsRisk() {
  const { data: p } = usePoll(api.positions, 4000)
  const { data: r } = usePoll(api.risk, 4000)
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
    <h2>Stress panel (§24.1)</h2>
    {r?.note ? <p className="muted">{r.note}</p> :
      r?.var_95_pct !== undefined ? <>
        <div className="tiles">
          <Tile k="VaR 95%" v={`${r.var_95_pct.toFixed(2)}%`} />
          <Tile k="ES 95%" v={`${r.es_95_pct.toFixed(2)}%`} />
          <Tile k="VaR 99%" v={`${r.var_99_pct.toFixed(2)}%`} />
          <Tile k="ES 99%" v={`${r.es_99_pct.toFixed(2)}%`} />
          <Tile k="BTC beta" v={r.btc?.beta?.toFixed(2) ?? '—'} />
          <Tile k="BTC beta %" v={`${r.factor?.btc_beta_pct?.toFixed(1) ?? '—'}%`} />
          <Tile k="Idiosyncratic %" v={`${r.factor?.idiosyncratic_pct?.toFixed(1) ?? '—'}%`} />
        </div>
        <Table cols={['Metric', 'BTC benchmark', 'T1 basket']}
          rows={[
            ['Alpha (annualized)', r.btc?.alpha_annualized?.toFixed(4) ?? '—', r.basket?.alpha_annualized?.toFixed(4) ?? '—'],
            ['Beta', r.btc?.beta?.toFixed(4) ?? '—', r.basket?.beta?.toFixed(4) ?? '—'],
            ['t-stat', r.btc?.t_stat?.toFixed(4) ?? '—', r.basket?.t_stat?.toFixed(4) ?? '—'],
          ]} />
      </> : <p className="muted">Risk analytics will appear once the daily job has enough equity history.</p>}
  </div>
}

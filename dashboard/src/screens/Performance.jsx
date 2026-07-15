import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { Tile, Spark, Empty } from '../components/ui'
export default function Performance() {
  const [eq, setEq] = useState(null); const [s, setS] = useState(null)
  useEffect(() => { api.equity().then(setEq); api.stats().then(setS) }, [])
  const curve = eq?.equity || []
  return <div className="page"><h1>Performance</h1>
    <div className="tiles">
      <Tile k="Decisions" v={s?.n_decisions ?? '—'} />
      <Tile k="Traded" v={s?.n_traded ?? '—'} />
      <Tile k="NO_TRADE rate" v={s ? (s.no_trade_rate * 100).toFixed(0) + '%' : '—'} />
    </div>
    <h2>Equity curve</h2>
    {curve.length > 1 ? <Spark points={curve} /> : <Empty what="equity points" />}
  </div>
}

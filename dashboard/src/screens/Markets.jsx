import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Badge, Table, Empty } from '../components/ui'
export default function Markets() {
  const [rows, setRows] = useState(null)
  useEffect(() => { api.decisions(50).then(d => {
    if (!d) return setRows([])
    const bySym = {}
    for (const x of d.decisions) if (!bySym[x.symbol]) bySym[x.symbol] = x
    setRows(Object.values(bySym))
  }) }, [])
  if (!rows) return <div className="page">loading…</div>
  return <div className="page"><h1>Markets</h1>
    {rows.length === 0 ? <Empty what="decisions" /> :
      <Table cols={['Asset', 'Regime', 'p_up', 'Confidence', 'Opportunity', 'Risk', 'Action']}
        rows={rows.map(r => {
          const u = r.record.understanding
          return [<Link to={`/asset/${r.symbol}`}>{r.symbol}</Link>, <Badge dir={u.regime}>{u.regime}</Badge>,
            u.p_up.toFixed(3), (u.confidence * 100).toFixed(0) + '%', u.opportunity_score.toFixed(0),
            u.risk_score.toFixed(0), <Badge dir={r.record.chosen.action}>{r.record.chosen.action}</Badge>]
        })} />}
  </div>
}

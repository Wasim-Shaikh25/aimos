import React from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Badge, Table, Empty } from '../components/ui'
export default function Markets() {
  const { data } = usePoll(() => api.decisions(400), 4000)
  if (data === undefined) return <div className="page">loading…</div>
  const bySym = {}
  for (const x of (data?.decisions || [])) if (!bySym[x.symbol]) bySym[x.symbol] = x
  const rows = Object.values(bySym).sort((a, b) => a.symbol.localeCompare(b.symbol))
  return <div className="page"><h1>Markets <span className="muted" style={{ fontSize: 14 }}>({rows.length} assets)</span></h1>
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

import React from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Badge, Table, Empty } from '../components/ui'
export default function Decisions() {
  const { data: d } = usePoll(() => api.decisions(100), 4000)
  if (d === undefined) return <div className="page">loading…</div>
  if (!d?.decisions?.length) return <div className="page"><h1>Decisions</h1><Empty what="decisions" /></div>
  return <div className="page"><h1>Decisions</h1>
    <Table cols={['Time', 'Symbol', 'Regime', 'p_up', 'Plugin', 'Action', 'Score']}
      rows={d.decisions.map(x => { const u = x.record.understanding, c = x.record.chosen
        return [<span className="mono">{x.timestamp?.slice(0, 19)}</span>, x.symbol, <Badge dir={u.regime}>{u.regime}</Badge>,
          u.p_up.toFixed(3), c.plugin, <Badge dir={c.action}>{c.action}</Badge>, c.score?.toFixed(2)] })} />
  </div>
}

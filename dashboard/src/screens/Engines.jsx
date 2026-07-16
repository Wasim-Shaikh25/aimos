import React, { useState } from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Badge, Table, Empty } from '../components/ui'

// The 13 observation engines (§5). Shows the live evidence each engine emitted
// for the selected asset on the latest tick — strength × reliability, direction.
export default function Engines() {
  const { data: mk } = usePoll(api.markets, 4000)
  const [sym, setSym] = useState(null)
  const assets = (mk?.markets || []).map(m => m.symbol).sort()
  const active = sym || assets[0]
  const { data: ev } = usePoll(() => active ? api.evidence(active) : Promise.resolve(null), 4000, [active])
  const rows = ev?.evidences || []
  const engines = [...new Set(rows.map(e => e.source?.split('.')[0]))]
  return <div className="page"><h1>Observation Engines</h1>
    <p className="muted">The 13 sensor engines each emit typed evidence per tick (§5). Select an asset to see its latest evidence — {engines.length} engines reporting.</p>
    <label className="muted">Asset&nbsp;
      <select value={active || ''} onChange={e => setSym(e.target.value)}>
        {assets.map(a => <option key={a} value={a}>{a}</option>)}
      </select>
    </label>
    {rows.length === 0 ? <div style={{ marginTop: 16 }}><Empty what="evidence" /></div> :
      <div style={{ marginTop: 16 }}><Table
        cols={['Engine', 'Evidence', 'Direction', 'Value', 'Strength', 'Reliability']}
        rows={rows.map(e => [
          e.source?.split('.')[0],
          e.name,
          <Badge dir={e.direction}>{e.direction}</Badge>,
          Number(e.value).toFixed(3),
          Number(e.strength).toFixed(2),
          Number(e.reliability).toFixed(2),
        ])} /></div>}
  </div>
}

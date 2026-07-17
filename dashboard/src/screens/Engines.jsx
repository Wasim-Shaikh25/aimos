import React, { useState } from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Badge, Table, Empty } from '../components/ui'

// The 13 observation engines (§5). Per asset AND per venue — the same pipeline
// runs on every platform, so you can compare a coin's evidence across venues.
export default function Engines() {
  const { data: mk } = usePoll(api.markets, 4000)
  const [sym, setSym] = useState(null)
  const [venue, setVenue] = useState(null)
  const assets = (mk?.markets || []).map(m => m.symbol).sort()
  const active = sym || assets[0]
  const { data: ev } = usePoll(() => active ? api.evidence(active, venue) : Promise.resolve(null), 4000, [active, venue])
  const rows = ev?.evidences || []
  const venues = ev?.venues || []
  const engines = [...new Set(rows.map(e => e.source?.split('.')[0]))]
  return <div className="page"><h1>Observation Engines</h1>
    <p className="muted">The 13 sensor engines emit typed evidence per tick (§5), on every venue. {engines.length} engines reporting.</p>
    <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 12 }}>
      <label className="muted">Asset&nbsp;
        <select value={active || ''} onChange={e => setSym(e.target.value)}>
          {assets.map(a => <option key={a} value={a}>{a}</option>)}
        </select>
      </label>
      <label className="muted">Venue&nbsp;
        <select value={venue || ''} onChange={e => setVenue(e.target.value || null)}>
          <option value="">primary</option>
          {venues.map(v => <option key={v} value={v}>{v}</option>)}
        </select>
      </label>
    </div>
    {rows.length === 0 ? <Empty what="evidence" /> :
      <Table cols={['Engine', 'Evidence', 'Direction', 'Value', 'Strength', 'Reliability']}
        rows={rows.map(e => [
          e.source?.split('.')[0], e.name,
          <Badge dir={e.direction}>{e.direction}</Badge>,
          Number(e.value).toFixed(3), Number(e.strength).toFixed(2), Number(e.reliability).toFixed(2),
        ])} />}
  </div>
}

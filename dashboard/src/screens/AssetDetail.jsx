import React from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Badge, Gauge } from '../components/ui'
export default function AssetDetail() {
  const { base } = useParams()
  const { data: u } = usePoll(() => api.state(base), 4000, [base])
  if (!u) return <div className="page"><h1>{base}</h1><p className="muted">no state — /api/state/{base}</p></div>
  return <div className="page"><h1>{base} <Badge dir={u.regime}>{u.regime}</Badge></h1>
    <p>p_up <b>{u.p_up?.toFixed(3)}</b> · behavior {u.behavior} · bias {u.direction_bias}</p>
    <div style={{ maxWidth: 320 }}>confidence<Gauge value={u.confidence} /></div>
    <h2>Reasons</h2><ul className="mono">{(u.reasons || []).map((r, i) => <li key={i}>{r}</li>)}</ul>
  </div>
}

import React, { useState } from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Badge } from '../components/ui'

// Go-live ladder (§23.8): progress toward real-money trading. Each gate is an
// operator sign-off; live is allowed ONLY when all gates pass. Time-based gates
// show auto progress but still need an explicit confirm — nothing goes live on a timer.
export default function GoLive() {
  const { data } = usePoll(api.golive, 5000)
  const [busy, setBusy] = useState(null)
  if (!data) return <div className="page">loading…</div>
  const gates = data.gates || []

  async function mark(gate, passed) {
    setBusy(gate); await api.setGolive(gate, passed); setBusy(null)
  }

  return <div className="page"><h1>Go-Live Progress</h1>
    <p className="muted">Real-money trading unlocks only when <b>every</b> gate is signed off (§23.8). This is a
      deliberate operator process — flags on the Controls screen can never flip live trading.</p>

    <div style={{ margin: '14px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <span className="muted">{data.passed} / {data.total} gates · next: <b>{data.next || 'none — complete'}</b></span>
        <span><b>{data.percent}%</b></span>
      </div>
      <div className="gauge" style={{ height: 12 }}><i style={{ width: `${data.percent}%`,
        background: data.live_allowed ? 'var(--green)' : 'var(--blue)' }} /></div>
      <p style={{ marginTop: 8 }}>
        Live trading: <Badge dir={data.live_allowed ? 'up' : 'down'}>
          {data.live_allowed ? 'ALLOWED (all gates passed)' : 'LOCKED'}</Badge></p>
    </div>

    <table><thead><tr><th>Gate</th><th>Status</th><th>Auto progress</th><th>Action</th></tr></thead>
      <tbody>{gates.map(g => <tr key={g.id}>
        <td><div><b>{g.title}</b></div><div className="muted" style={{ fontSize: 12 }}>{g.detail}</div>
          {g.marked_at && <div className="muted" style={{ fontSize: 11 }}>signed off {g.marked_at.slice(0, 19)}</div>}</td>
        <td><Badge dir={g.status === 'passed' ? 'up' : 'flat'}>{g.status}</Badge></td>
        <td style={{ minWidth: 160 }}>{g.progress == null ? <span className="muted">—</span> :
          <><div className="gauge"><i style={{ width: `${Math.round(g.progress * 100)}%` }} /></div>
            <div className="muted" style={{ fontSize: 11 }}>{g.hint}</div></>}</td>
        <td><button disabled={busy === g.id} onClick={() => mark(g.id, g.status !== 'passed')}>
          {busy === g.id ? '…' : (g.status === 'passed' ? 'Un-sign' : 'Sign off')}</button></td>
      </tr>)}</tbody></table>
  </div>
}

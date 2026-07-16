import React from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Table, Empty } from '../components/ui'

// The three reasoning models (§6) + learning status (§8). rule/bayes fuse by
// config weight; ml runs in shadow (weight 0) until it proves calibration.
export default function Models() {
  const { data } = usePoll(api.models, 5000)
  const rows = data?.models || []
  return <div className="page"><h1>Reasoning Models</h1>
    <p className="muted">Three independent opinions fused deterministically (§6.3). No LLM in the decision path (§15.3). The ML model stays at fusion weight 0 (shadow) until it clears the promotion checklist (§8.3).</p>
    {rows.length === 0 ? <Empty what="models" /> :
      <Table cols={['Model', 'Kind', 'Fusion weight', 'Avg p_up', 'Status']}
        rows={rows.map(m => [
          m.name, m.kind,
          m.fusion_weight == null ? '—' : Number(m.fusion_weight).toFixed(2),
          m.avg_p_up == null ? '—' : Number(m.avg_p_up).toFixed(3),
          m.status,
        ])} />}
    {data?.learning && <>
      <h2>Learning</h2>
      <pre className="mono" style={{ background: 'var(--panel)', padding: 14, borderRadius: 8, overflow: 'auto' }}>
        {JSON.stringify(data.learning, null, 2)}</pre></>}
  </div>
}

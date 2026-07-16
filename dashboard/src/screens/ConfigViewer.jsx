import React from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Tile, Empty } from '../components/ui'

// Effective, merged config (§16.2 / §23.12). Grouped by section rather than one
// raw blob, with the operational highlights surfaced up top.
export default function ConfigViewer() {
  const { data: c } = usePoll(api.config, 8000)
  if (c === undefined) return <div className="page">loading…</div>
  if (!c) return <div className="page"><h1>Config</h1><Empty what="effective config" /></div>
  const paper = c.paper || {}, features = c.features || {}
  const sections = Object.entries(c).filter(([, v]) => v && typeof v === 'object')
  return <div className="page"><h1>Config (effective values)</h1>
    <div className="tiles">
      <Tile k="Mode" v={features.mode || 'paper'} />
      <Tile k="Universe" v={paper.use_universe ? `top ${paper.max_symbols}` : 'dev set'} />
      <Tile k="Data venue" v={paper.data_exchange} />
      <Tile k="Cross venues" v={(paper.cross_venues || []).join(', ') || '—'} />
    </div>
    <p className="muted">{sections.length} config sections. Every value is env-overridable via AIMOS__SECTION__KEY.</p>
    {sections.map(([name, val]) =>
      <details key={name} style={{ marginBottom: 8 }}>
        <summary className="mono" style={{ cursor: 'pointer', padding: '6px 0' }}>{name}</summary>
        <pre className="mono" style={{ background: 'var(--panel)', padding: 14, borderRadius: 8, overflow: 'auto' }}>
          {JSON.stringify(val, null, 2)}</pre>
      </details>)}
  </div>
}

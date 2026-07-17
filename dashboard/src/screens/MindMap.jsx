import React, { useState } from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Empty } from '../components/ui'

// Decision mind-map (§5.3): a node graph of one decision — engines → fusion →
// regime → eligible strategies → chosen — with the reasons ("why") below.
const LAYERS = ['Engines', 'Fusion', 'Regime', 'Strategies', 'Decision']
const COLORS = { engine: '#4c8dff', fusion: '#a06bff', regime: '#f5a623', strategy: '#2ec27e', decision: '#e6e9ef' }

export default function MindMap() {
  const { data: dec } = usePoll(() => api.decisions(60), 5000)
  const [id, setId] = useState(null)
  const decisions = dec?.decisions || []
  const activeId = id || decisions[0]?.decision_id
  const { data: g } = usePoll(() => activeId ? api.graph(activeId) : Promise.resolve(null), 5000, [activeId])

  if (!decisions.length) return <div className="page"><h1>Decision Mind-map</h1><Empty what="decisions" /></div>
  if (!g || !g.nodes?.length) return <div className="page"><h1>Decision Mind-map</h1><p className="muted">loading…</p></div>

  const W = 1140, colW = W / 5, nodeW = 150, nodeH = 48, rowGap = 78, top = 40
  const byLayer = {}
  g.nodes.forEach(n => { (byLayer[n.layer] = byLayer[n.layer] || []).push(n) })
  const maxRows = Math.max(...Object.values(byLayer).map(a => a.length), 1)
  const H = top * 2 + maxRows * rowGap
  const pos = {}
  Object.entries(byLayer).forEach(([layer, arr]) => {
    const L = +layer, cx = colW * L + colW / 2, colH = arr.length * rowGap
    const startY = (H - colH) / 2 + rowGap / 2
    arr.forEach((n, i) => { pos[n.id] = { x: cx - nodeW / 2, cx, cy: startY + i * rowGap } })
  })

  return <div className="page"><h1>Decision Mind-map <span className="muted" style={{ fontSize: 14 }}>{g.symbol}</span></h1>
    <label className="muted">Decision&nbsp;
      <select value={activeId} onChange={e => setId(e.target.value)}>
        {decisions.map(d => <option key={d.decision_id} value={d.decision_id}>{d.symbol} · {d.timestamp?.slice(0, 19)}</option>)}
      </select></label>
    <div style={{ overflowX: 'auto', marginTop: 12 }}>
      <svg width={W} height={H} style={{ background: 'var(--panel)', borderRadius: 8, minWidth: W }}>
        {LAYERS.map((l, i) => <text key={l} x={colW * i + colW / 2} y={22} fill="var(--muted)" fontSize="12" textAnchor="middle">{l}</text>)}
        {g.edges.map((e, i) => {
          const a = pos[e.from], b = pos[e.to]
          if (!a || !b) return null
          const x1 = a.x + nodeW, x2 = b.x, mx = (x1 + x2) / 2
          return <path key={i} d={`M${x1},${a.cy} C${mx},${a.cy} ${mx},${b.cy} ${x2},${b.cy}`}
            fill="none" stroke="var(--line)" strokeWidth="1.5" />
        })}
        {g.nodes.map(n => {
          const p = pos[n.id], c = COLORS[n.kind] || 'var(--text)'
          return <g key={n.id}>
            <rect x={p.x} y={p.cy - nodeH / 2} width={nodeW} height={nodeH} rx={8} fill="#161b22"
              stroke={n.highlight ? c : 'var(--line)'} strokeWidth={n.highlight ? 2.5 : 1} />
            <text x={p.cx} y={p.cy - 3} fill={c} fontSize="13" fontWeight="600" textAnchor="middle">{n.label}</text>
            <text x={p.cx} y={p.cy + 14} fill="var(--muted)" fontSize="11" textAnchor="middle">{n.sub}</text>
          </g>
        })}
      </svg>
    </div>
    <h2>Why this decision</h2>
    <ul className="mono">{(g.reasons || []).map((r, i) => <li key={i}>{r}</li>)}</ul>
  </div>
}

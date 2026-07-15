import React from 'react'
export const Badge = ({ dir, children }) => {
  const c = dir === 'bullish' || dir === 'up' || dir === 'long' || dir === 'trending_up' ? 'b-up'
    : dir === 'bearish' || dir === 'down' || dir === 'short' || dir === 'trending_down' || dir === 'crash' ? 'b-down' : 'b-flat'
  return <span className={`badge ${c}`}>{children ?? dir}</span>
}
export const Tile = ({ k, v }) => <div className="tile"><div className="k">{k}</div><div className="v">{v}</div></div>
export const Gauge = ({ value }) => <div className="gauge"><i style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} /></div>
export const Table = ({ cols, rows }) => (
  <table><thead><tr>{cols.map(c => <th key={c}>{c}</th>)}</tr></thead>
  <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody></table>
)
export const Empty = ({ what }) => <p className="muted">no {what} yet — start the paper loop to populate the journal.</p>
export const Spark = ({ points, w = 600, h = 120, color = '#4c8dff' }) => {
  if (!points || points.length < 2) return <p className="muted">no series</p>
  const min = Math.min(...points), max = Math.max(...points), rng = max - min || 1
  const path = points.map((p, i) => `${(i / (points.length - 1)) * w},${h - ((p - min) / rng) * h}`).join(' ')
  return <svg width={w} height={h} style={{ background: 'var(--panel)', borderRadius: 8 }}>
    <polyline fill="none" stroke={color} strokeWidth="2" points={path} /></svg>
}

import React from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Tile, Badge, Empty } from '../components/ui'
export default function UniverseMatrix() {
  const { data: u } = usePoll(api.matrix, 5000)
  if (u === undefined) return <div className="page">loading…</div>
  const matrix = u?.matrix || {}
  if (!Object.keys(matrix).length) return <div className="page"><h1>Universe & Venues</h1><Empty what="universe snapshot" /></div>
  const venues = [...new Set(Object.values(matrix).flatMap(v => Object.keys(v)))].sort()
  const bases = Object.keys(matrix).sort((a, b) =>
    (u.selected?.indexOf(a) + 1 || 1e9) - (u.selected?.indexOf(b) + 1 || 1e9) || a.localeCompare(b))
  const rej = u.rejections || {}
  return <div className="page"><h1>Universe &amp; Venues</h1>
    <div className="tiles">
      <Tile k="Discovered" v={u.total_discovered} />
      <Tile k="Analyzing (top-N)" v={u.selected?.length ?? '—'} />
      <Tile k="Cross-venue (≥2)" v={u.cross_venue_bases?.length ?? '—'} />
      <Tile k="Source" v={u.source} />
    </div>
    <p className="muted">Cross-exchange venues sampled: {(u.cross_venues || []).join(', ') || '—'}.
      {Object.keys(rej).length ? ` Rejected: ${Object.entries(rej).map(([k, v]) => `${v} ${k}`).join(', ')}.` : ''}</p>
    <table><thead><tr><th>Asset</th><th>Tier</th>{venues.map(v => <th key={v}>{v}</th>)}</tr></thead>
      <tbody>{bases.map(base => <tr key={base}>
        <td>{u.selected?.includes(base) ? <b>{base}</b> : base}</td>
        <td><Badge dir={u.tiers?.[base] === 't1' ? 'up' : 'flat'}>{u.tiers?.[base] || '—'}</Badge></td>
        {venues.map(v => <td key={v}>{matrix[base][v] ? '✅' : '—'}</td>)}</tr>)}</tbody></table>
  </div>
}

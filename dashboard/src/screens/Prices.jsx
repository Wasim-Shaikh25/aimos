import React from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Badge, Empty } from '../components/ui'

// Multi-platform price matrix (§5.1): each coin's live mid on every venue it
// trades on, the cross-venue dislocation (cheap→rich), and the per-venue
// decision — so you can see values AND what each platform's data implies.
export default function Prices() {
  const { data } = usePoll(api.prices, 4000)
  if (data === undefined) return <div className="page">loading…</div>
  const venues = data?.venues || []
  const rows = data?.rows || []
  if (!rows.length) return <div className="page"><h1>Prices &amp; Venues</h1><Empty what="price matrix" /></div>
  return <div className="page"><h1>Multi-platform Prices <span className="muted" style={{ fontSize: 14 }}>({rows.length} coins × {venues.length} venues)</span></h1>
    <p className="muted">Live mid per venue + cross-venue dislocation (bps) and the per-venue decision. A dislocation above round-trip cost is an arb candidate.</p>
    <div style={{ overflowX: 'auto' }}>
    <table><thead><tr>
      <th>Asset</th>
      {venues.map(v => <th key={v}>{v}</th>)}
      <th>Disloc (bps)</th><th>Cheap→Rich</th>
    </tr></thead>
    <tbody>{rows.map(r => {
      const disl = r.dislocation_bps
      return <tr key={r.base}>
        <td><Link to={`/asset/${r.base}`}>{r.base}</Link></td>
        {venues.map(v => {
          const mid = r.venues?.[v]
          const d = r.decisions?.[v]
          return <td key={v}>
            {mid == null ? <span className="muted">—</span> : <>
              <div className="mono">{mid.toLocaleString(undefined, { maximumFractionDigits: 4 })}</div>
              {d && <span style={{ fontSize: 11 }}><Badge dir={d.regime}>{d.action}</Badge></span>}
            </>}
          </td>
        })}
        <td className="mono" style={{ color: disl >= 20 ? 'var(--amber)' : 'var(--muted)' }}>
          {disl != null ? disl.toFixed(1) : '—'}</td>
        <td className="muted" style={{ fontSize: 12 }}>{r.cheap ? `${r.cheap} → ${r.rich}` : '—'}</td>
      </tr>
    })}</tbody></table>
    </div>
  </div>
}

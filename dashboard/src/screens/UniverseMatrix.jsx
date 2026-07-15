import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { Empty } from '../components/ui'
export default function UniverseMatrix() {
  const [m, setM] = useState(undefined)
  useEffect(() => { api.matrix().then(setM) }, [])
  if (m === undefined) return <div className="page">loading…</div>
  if (!m || !Object.keys(m).length) return <div className="page"><h1>Universe & Venues</h1><Empty what="universe snapshot" /></div>
  const venues = [...new Set(Object.values(m).flatMap(v => Object.keys(v)))]
  return <div className="page"><h1>Universe & Venues</h1>
    <table><thead><tr><th>Asset</th>{venues.map(v => <th key={v}>{v}</th>)}</tr></thead>
    <tbody>{Object.entries(m).map(([base, row]) => <tr key={base}><td>{base}</td>
      {venues.map(v => <td key={v}>{row[v] ? '✅' : row[v] === false ? '—' : ''}</td>)}</tr>)}</tbody></table>
  </div>
}

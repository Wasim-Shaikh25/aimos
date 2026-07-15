import React, { useEffect, useState } from 'react'
// AssetDetail — §16.2/§18.5. Renders against the journal-backed API (§15.1).
export default function AssetDetail() {
  const [data, setData] = useState(null)
  useEffect(() => { fetch('/api/decisions?limit=20').then(r => r.json()).then(setData).catch(() => {}) }, [])
  return <div style={{ padding: 16 }}><h1>AssetDetail</h1>
    <pre style={{ maxHeight: 400, overflow: 'auto' }}>{data ? JSON.stringify(data, null, 2) : 'loading…'}</pre></div>
}

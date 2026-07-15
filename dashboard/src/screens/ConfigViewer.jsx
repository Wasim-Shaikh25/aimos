import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { Empty } from '../components/ui'
export default function ConfigViewer() {
  const [c, setC] = useState(undefined)
  useEffect(() => { api.config().then(setC) }, [])
  if (c === undefined) return <div className="page">loading…</div>
  if (!c) return <div className="page"><h1>Config</h1><Empty what="effective config" /></div>
  return <div className="page"><h1>Config (effective values)</h1>
    <pre className="mono" style={{ background: 'var(--panel)', padding: 14, borderRadius: 8, overflow: 'auto' }}>
      {JSON.stringify(c, null, 2)}</pre></div>
}

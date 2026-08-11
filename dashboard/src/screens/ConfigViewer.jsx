import React from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Table, Tile } from '../components/ui'

function ConfigValue({ value }) {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.join(', ') || '—'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'object') {
    return (
      <dl className="space-y-0.5 pl-2 border-l border-border">
        {Object.entries(value).map(([k, v]) => (
          <div key={k} className="flex justify-between gap-2 text-xs">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="font-mono"><ConfigValue value={v} /></dd>
          </div>
        ))}
      </dl>
    )
  }
  return String(value)
}

export default function ConfigViewer() {
  const { data: c } = usePoll(api.config, 8000)
  if (c === undefined) return <div className="page"><h1>Config</h1><p className="text-muted-foreground">loading…</p></div>
  if (!c) return <div className="page"><h1>Config</h1><p className="text-muted-foreground">no effective config</p></div>
  const paper = c.paper || {}
  const features = c.features || {}
  const sections = Object.entries(c).filter(([, v]) => v && typeof v === 'object')
  return <div className="page animate-fade-in">
    <div className="mb-4">
      <h1>Config (effective values)</h1>
      <p className="text-sm text-muted-foreground">{sections.length} config sections. Every value is env-overridable via <code className="font-mono">AIMOS__SECTION__KEY</code>.</p>
    </div>
    <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-4">
      <Tile k="Mode" v={features.mode || 'paper'} />
      <Tile k="Universe" v={paper.use_universe ? `top ${paper.max_symbols}` : 'dev set'} />
      <Tile k="Data venue" v={paper.data_exchange || '—'} />
      <Tile k="Cross venues" v={(paper.cross_venues || []).join(', ') || '—'} />
    </div>
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {sections.map(([name, val]) =>
        <Card key={name}>
          <CardHeader>
            <CardTitle className="capitalize">{name}</CardTitle>
            <CardDescription>{Object.keys(val).length} keys</CardDescription>
          </CardHeader>
          <CardContent>
            <Table
              cols={['Key', { label: 'Value', align: 'right' }]}
              rows={Object.entries(val).map(([k, v]) => [k, <ConfigValue key={k} value={v} />])}
            />
          </CardContent>
        </Card>
      )}
    </div>
  </div>
}

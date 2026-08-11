import React from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Table, Tile } from '../components/ui'

function LearningValue({ value }) {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.join(', ') || '—'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'object') {
    return (
      <dl className="space-y-0.5 pl-2 border-l border-border">
        {Object.entries(value).map(([k, v]) => (
          <div key={k} className="flex justify-between gap-2 text-xs">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="font-mono"><LearningValue value={v} /></dd>
          </div>
        ))}
      </dl>
    )
  }
  return String(value)
}

export default function Models() {
  const { data } = usePoll(api.models, 5000)
  const rows = data?.models || []
  return <div className="page animate-fade-in">
    <div className="mb-4">
      <h1>Reasoning Models</h1>
      <p className="text-sm text-muted-foreground">Three independent opinions fused deterministically (§6.3). No LLM in the decision path (§15.3). The ML model stays at fusion weight 0 (shadow) until it clears the promotion checklist (§8.3).</p>
    </div>
    {rows.length === 0 ? <p className="text-sm text-muted-foreground">no models yet — start the paper loop to populate the journal.</p> :
      <Table cols={['Model', 'Kind', 'Fusion weight', 'Avg p_up', 'Status']}
        rows={rows.map(m => [
          m.name, m.kind,
          m.fusion_weight == null ? '—' : Number(m.fusion_weight).toFixed(2),
          m.avg_p_up == null ? '—' : Number(m.avg_p_up).toFixed(3),
          <Badge key="s" dir={m.status === 'active' ? 'up' : 'down'}>{m.status}</Badge>,
        ])} />}
    {data?.learning && <>
      <h2 className="mt-6">Learning</h2>
      <Card>
        <CardHeader>
          <CardTitle>Training status</CardTitle>
          <CardDescription>Live metrics from the ML shadow pipeline.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-4 mb-4">
            <Tile k="Dataset" v={data.learning.dataset || '—'} />
            <Tile k="Samples" v={data.learning.samples ?? '—'} />
            <Tile k="AUC" v={data.learning.auc != null ? data.learning.auc.toFixed(3) : '—'} />
            <Tile k="Status" v={data.learning.status || '—'} />
          </div>
          <Table
            cols={['Metric', { label: 'Value', align: 'right' }]}
            rows={Object.entries(data.learning).map(([k, v]) => [k, <LearningValue key={k} value={v} />])}
          />
        </CardContent>
      </Card>
    </>}
  </div>
}

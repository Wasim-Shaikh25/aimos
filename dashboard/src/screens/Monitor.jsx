import React from 'react'
import { api } from '../api'
import { usePoll, ago } from '../hooks'
import { Badge, Table, Gauge } from '../components/ui'

// Feature monitor agent — the background self-tester. Probes every feature on an
// interval and reports ok / degraded / failing, plus a coverage %. When
// force_coverage is on it enables the safe keyless flags (cross_exchange, scalp)
// so every path is exercised without waiting for organic market conditions.
const dirFor = (s) => (s === 'ok' ? 'up' : s === 'failing' ? 'down' : 'flat')

export default function Monitor() {
  const { data, updatedAt } = usePoll(api.monitor, 5000)
  const feats = data?.features || []
  const sum = data?.summary || {}
  const cov = data?.coverage_pct ?? 0
  return <div className="page"><h1>Feature Monitor</h1>
    <p className="muted">A background agent probes every feature on an interval and reports
      health, so you can see at a glance what's exercised. <b>Forced coverage</b> flips the safe
      keyless flags (cross_exchange, scalp) on to drive every path. It never touches live/funded
      features. Report also at <code className="mono">/api/monitor</code> and
      <code className="mono"> state/monitor_report.json</code>.</p>

    {feats.length === 0
      ? <p className="muted">{data?.note || 'Monitor not running — set '}
        {!data?.note && <code className="mono">monitor.enabled: true</code>}
        {!data?.note && ' (config/default.yaml) or '}
        {!data?.note && <code className="mono">AIMOS__MONITOR__ENABLED=true</code>}
        {!data?.note && ' and restart.'}</p>
      : <>
        <div className="row" style={{ gap: 24, alignItems: 'center', margin: '12px 0' }}>
          <div style={{ flex: 1, maxWidth: 420 }}>
            <div className="k">Coverage <b>{cov}%</b> {data?.forced ? <Badge dir="up">forced</Badge> : null}</div>
            <Gauge value={cov / 100} />
          </div>
          <span className="stat">ok <b className="b-up badge">{sum.ok ?? 0}</b></span>
          <span className="stat">degraded <b className="b-flat badge">{sum.degraded ?? 0}</b></span>
          <span className="stat">failing <b className="b-down badge">{sum.failing ?? 0}</b></span>
          <span className="stat live"><i className="dot" /> <b>{ago(updatedAt)}</b></span>
        </div>
        <Table cols={['Feature', 'Status', 'Detail']}
          rows={feats.map(f => [
            f.name,
            <Badge dir={dirFor(f.status)}>{f.status}</Badge>,
            <span className="muted">{f.detail}</span>,
          ])} />
      </>}
  </div>
}

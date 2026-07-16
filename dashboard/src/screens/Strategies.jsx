import React from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Badge, Table, Empty } from '../components/ui'

// Execution plugins (§7). Every registered strategy, its gating config, and how
// many times it was chosen this run. Disabled plugins show why they're dormant.
export default function Strategies() {
  const { data } = usePoll(api.strategies, 5000)
  const rows = data?.strategies || []
  return <div className="page"><h1>Strategies (execution plugins)</h1>
    <p className="muted">Competing proposer agents (§7.2). Each proposes trade geometry only in its regime; the evaluator picks the positive-EV winner or NO_TRADE. RiskOff always runs first.</p>
    {rows.length === 0 ? <Empty what="strategies" /> :
      <Table cols={['Strategy', 'Enabled', 'Regimes', 'Min conf', 'Min health', 'Chosen']}
        rows={rows.map(s => [
          s.name,
          s.enabled ? <Badge dir="up">on</Badge> : <Badge dir="down">off</Badge>,
          (s.regimes || []).join(', '),
          Number(s.min_confidence).toFixed(2),
          Number(s.min_coin_health).toFixed(0),
          s.chosen,
        ])} />}
  </div>
}

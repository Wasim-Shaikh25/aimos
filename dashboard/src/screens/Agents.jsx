import React from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Table, Empty } from '../components/ui'
export default function Agents() {
  const { data: a } = usePoll(api.agents, 6000)
  const { data: p } = usePoll(api.proposals, 6000)
  return <div className="page"><h1>Agents</h1>
    <h2>Roster</h2>
    {a?.agents?.length ? <Table cols={['Agent', 'Status', 'Last run']}
      rows={a.agents.map(x => [x.name, x.status, x.last_run])} /> :
      <p className="muted">Agents (A1 Analyst · A2 Sentinel · A3 Ops) are Phase-6, feature-flagged off. Enable in config to populate.</p>}
    <h2>Proposals</h2>
    {p?.proposals?.length ? <Table cols={['ID', 'Title', 'Status']} rows={p.proposals.map(x => [x.proposal_id, x.title, x.status])} />
      : <Empty what="proposals" />}
  </div>
}

import React from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Tile, Table, Empty } from '../components/ui'

// Balance check (§5.4): per-venue simulated balances. Live balances arrive when
// read-only keys are configured + the Phase-D startup preflight verifies them.
export default function Balances() {
  const { data } = usePoll(api.balances, 4000)
  const venues = data?.venues || []
  return <div className="page"><h1>Balances (per venue)</h1>
    <p className="muted">{data?.note || 'per-venue balances'}. Arb shifts USDT from the buy venue to the sell venue — which is why live arb needs inventory on both sides.</p>
    <div className="tiles">
      <Tile k="Total USDT" v={`$${Number(data?.total_usdt ?? 0).toFixed(2)}`} />
      <Tile k="Venues" v={venues.length} />
      <Tile k="Directional cash" v={`$${Number(data?.directional_cash ?? 0).toFixed(2)}`} />
    </div>
    {venues.length === 0 ? <Empty what="balances" /> :
      <Table cols={['Venue', 'USDT', 'Other assets']}
        rows={venues.map(v => [
          v.venue,
          `$${Number(v.usdt).toFixed(2)}`,
          Object.keys(v.assets || {}).length
            ? Object.entries(v.assets).map(([a, q]) => `${a}: ${q}`).join(', ') : '—',
        ])} />}
  </div>
}

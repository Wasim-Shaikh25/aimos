import React from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Badge, Table } from '../components/ui'

// Venue connections (Phase D §2.4): the read-only startup self-check. Shows per
// venue whether the key connects, can trade (withdrawals disabled), and its
// balance — never the secret itself. Empty until you add keys.
export default function Connections() {
  const { data } = usePoll(api.connections, 6000)
  const venues = data?.venues || []
  return <div className="page"><h1>Venue Connections</h1>
    <p className="muted">Read-only startup preflight — authenticates each configured key, fetches balance,
      and verifies withdrawals are disabled. <b>No orders are ever placed.</b> Keys are only used here,
      never for market-data analysis, and never shown in the UI.</p>
    {venues.length === 0
      ? <p className="muted">No venue keys configured. Add them via <code className="mono">AIMOS_SECRETS_FILE</code> (a
        <code className="mono"> secrets.yaml</code>) or <code className="mono">AIMOS_KEY_&lt;VENUE&gt;</code> /
        <code className="mono">AIMOS_SECRET_&lt;VENUE&gt;</code> env vars, then restart. Paper trading and price
        monitoring need no keys.</p>
      : <Table cols={['Venue', 'Configured', 'Connected', 'Withdrawals disabled', 'Can trade', 'USDT free', 'Error']}
        rows={venues.map(v => [
          v.venue,
          v.configured ? '✅' : '—',
          <Badge dir={v.connected ? 'up' : 'down'}>{v.connected ? 'connected' : 'no'}</Badge>,
          v.withdrawal_disabled == null ? '—' : (v.withdrawal_disabled ? '✅' : '⚠️ can withdraw'),
          <Badge dir={v.can_trade ? 'up' : 'flat'}>{v.can_trade ? 'yes' : 'no'}</Badge>,
          v.usdt_free != null ? `$${Number(v.usdt_free).toFixed(2)}` : '—',
          v.error || '',
        ])} />}
  </div>
}

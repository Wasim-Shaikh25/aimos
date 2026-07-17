import React, { useState } from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Badge } from '../components/ui'

// Runtime feature toggles (UI + Telegram). Safe, keyless flags flip live (they
// rebuild the engines/plugins on the next tick); live/funded flags are LOCKED and
// stay behind the §23.8 go-live ladder — never a button.
export default function Controls() {
  const { data } = usePoll(api.features, 4000)
  const [busy, setBusy] = useState(null)
  const feats = data?.features || {}
  const toggleable = data?.toggleable || []
  const locked = data?.locked || {}

  async function flip(name, next) {
    setBusy(name)
    await api.setFeature(name, next)
    setBusy(null)
  }

  return <div className="page"><h1>Controls</h1>
    <p className="muted">Toggle the safe, keyless features at runtime — they take effect on the next tick,
      no restart. Live/funded features are locked here and require the §23.8 go-live ladder + funded keys.
      Everything here is also available on Telegram: <span className="mono">/features · /enable &lt;name&gt; · /disable &lt;name&gt;</span>.</p>

    <h2>Runtime-toggleable</h2>
    <table><thead><tr><th>Feature</th><th>State</th><th>Action</th></tr></thead>
      <tbody>{toggleable.map(name => {
        const on = !!feats[name]
        return <tr key={name}>
          <td className="mono">{name}</td>
          <td><Badge dir={on ? 'up' : 'flat'}>{on ? 'on' : 'off'}</Badge></td>
          <td><button disabled={busy === name} onClick={() => flip(name, !on)}>
            {busy === name ? '…' : (on ? 'Disable' : 'Enable')}</button></td>
        </tr>
      })}</tbody></table>

    <h2>Other flags (set in config, restart to apply)</h2>
    <table><thead><tr><th>Feature</th><th>State</th></tr></thead>
      <tbody>
        {['telegram', 'llm_news_sensor', 'live_data'].map(n =>
          <tr key={n}><td className="mono">{n}</td><td><Badge dir={feats[n] ? 'up' : 'flat'}>{feats[n] ? 'on' : 'off'}</Badge></td></tr>)}
      </tbody></table>

    <h2>Locked — require the go-live ladder + capital</h2>
    <table><thead><tr><th>Feature</th><th>Why it's locked</th></tr></thead>
      <tbody>{Object.entries(locked).map(([name, why]) =>
        <tr key={name}><td className="mono">🔒 {name}</td><td className="muted">{why}</td></tr>)}</tbody></table>
  </div>
}

import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth.jsx'
import { Tile, Empty } from '../components/ui'

const FEATURES = [
  ['live_data', 'Live market data (disable for offline paper)'],
  ['scalp_enabled', 'Scalp strategy'],
  ['cross_exchange_enabled', 'Cross-exchange arbitrage'],
  ['multi_venue_live', 'Multi-venue live execution (gated)'],
  ['streaming_enabled', 'Streaming websockets'],
  ['telegram_enabled', 'Telegram notifications'],
  ['llm_news_sensor', 'LLM news sensor'],
]

function Field({ label, type = 'text', value = '', onChange, required = false, placeholder = '' }) {
  return (
    <label style={{ display: 'block', marginBottom: 12 }}>
      <span style={{ display: 'block', color: 'var(--muted)', fontSize: 12, marginBottom: 4 }}>{label}</span>
      <input type={type} value={value || ''} onChange={e => onChange(e.target.value)}
        required={required} placeholder={placeholder}
        style={{ width: '100%', padding: '8px 10px', background: '#222836', color: 'var(--text)', border: '1px solid var(--line)', borderRadius: 6 }} />
    </label>
  )
}

function Toggle({ label, checked, onChange }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, cursor: 'pointer' }}>
      <input type="checkbox" checked={!!checked} onChange={e => onChange(e.target.checked)} />
      <span style={{ fontSize: 13 }}>{label}</span>
    </label>
  )
}

export default function Settings() {
  const { user, saasEnabled } = useAuth()
  const [settings, setSettings] = useState(null)
  const [draft, setDraft] = useState({})
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')

  // Exchange key form
  const [venue, setVenue] = useState('binance')
  const [apiKey, setApiKey] = useState('')
  const [secret, setSecret] = useState('')
  const [testnet, setTestnet] = useState(true)
  const [withdraw, setWithdraw] = useState(false)

  const load = async () => {
    const s = await api.settings()
    if (!s) return
    setSettings(s)
    setDraft({
      mode: s.mode || 'paper',
      features: s.features || {},
      paper: s.paper || {},
      mandate: s.mandate || {},
      training: s.training || { symbols: 'BTC/USDT,ETH/USDT', timeframe: '1h', months: 12 },
    })
  }

  useEffect(() => { load() }, [])

  const notify = (msg) => { setMessage(msg); setTimeout(() => setMessage(''), 3000) }

  const save = async (section, payload) => {
    setLoading(true)
    const res = await api.patchSettingsConfig({ [section]: payload })
    setLoading(false)
    if (res) { notify(`${section} saved`); await load() }
    else notify(`Failed to save ${section}`)
  }

  const addExchange = async (e) => {
    e.preventDefault()
    setLoading(true)
    const res = await api.addExchange({ venue, apiKey, secret, testnet, withdraw, exchange_id: venue })
    setLoading(false)
    if (res) {
      notify(`Added ${venue} key`)
      setApiKey(''); setSecret(''); await load()
    } else {
      notify('Failed to add exchange key')
    }
  }

  const removeExchange = async (v) => {
    setLoading(true)
    const res = await api.deleteExchange(v)
    setLoading(false)
    if (res) { notify(`Removed ${v}`); await load() }
    else notify('Failed to remove exchange key')
  }

  if (!saasEnabled) return (
    <div className="page"><h1>Settings</h1>
      <p className="muted">Settings are only available when SaaS is enabled.</p>
    </div>
  )

  if (!settings || !draft.mode) return <div className="page"><h1>Settings</h1><p className="muted">Loading…</p></div>

  const exchanges = settings.exchanges || {}

  return <div className="page">
    <h1>Settings</h1>
    {message && <p style={{ color: 'var(--green)', fontSize: 13 }}>{message}</p>}
    <div className="tiles">
      <Tile k="User" v={user?.email || user?.id || '—'} />
      <Tile k="Mode" v={draft.mode || 'paper'} />
      <Tile k="Configured exchanges" v={Object.keys(exchanges).length} />
    </div>

    <h2>Mode & features</h2>
    <div style={{ background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 8, padding: 16, marginBottom: 18 }}>
      <label style={{ display: 'block', marginBottom: 12 }}>
        <span style={{ display: 'block', color: 'var(--muted)', fontSize: 12, marginBottom: 4 }}>Trading mode</span>
        <select value={draft.mode} onChange={e => setDraft({ ...draft, mode: e.target.value })}
          style={{ width: '100%', padding: '8px 10px', background: '#222836', color: 'var(--text)', border: '1px solid var(--line)', borderRadius: 6 }}>
          <option value="paper">Paper</option>
          <option value="live">Live</option>
        </select>
      </label>
      {FEATURES.map(([key, label]) => (
        <Toggle key={key} label={label} checked={draft.features?.[key]} onChange={v => {
          setDraft({ ...draft, features: { ...draft.features, [key]: v } })
        }} />
      ))}
      <button onClick={() => save('mode', draft.mode)} disabled={loading} style={{ marginTop: 8, marginRight: 8 }}>Save mode</button>
      <button onClick={() => save('features', draft.features)} disabled={loading}>Save features</button>
    </div>

    <h2>Mandate (go-live guard)</h2>
    <div style={{ background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 8, padding: 16, marginBottom: 18 }}>
      <Toggle label="Enable mandate (required before live/testnet)" checked={draft.mandate?.enabled}
        onChange={v => setDraft({ ...draft, mandate: { ...draft.mandate, enabled: v } })} />
      <Field label="Max total notional (USDT)" type="number" value={draft.mandate?.max_total_notional_usdt}
        onChange={v => setDraft({ ...draft, mandate: { ...draft.mandate, max_total_notional_usdt: Number(v) } })} />
      <Field label="Max positions" type="number" value={draft.mandate?.max_positions}
        onChange={v => setDraft({ ...draft, mandate: { ...draft.mandate, max_positions: Number(v) } })} />
      <Field label="Max risk % per trade" type="number" value={draft.mandate?.max_risk_pct_per_trade}
        onChange={v => setDraft({ ...draft, mandate: { ...draft.mandate, max_risk_pct_per_trade: Number(v) } })} />
      <button onClick={() => save('mandate', draft.mandate)} disabled={loading}>Save mandate</button>
    </div>

    <h2>Paper config</h2>
    <div style={{ background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 8, padding: 16, marginBottom: 18 }}>
      <Field label="Starting equity (USDT)" type="number" value={draft.paper?.starting_equity_usdt}
        onChange={v => setDraft({ ...draft, paper: { ...draft.paper, starting_equity_usdt: Number(v) } })} />
      <Field label="Max symbols" type="number" value={draft.paper?.max_symbols}
        onChange={v => setDraft({ ...draft, paper: { ...draft.paper, max_symbols: Number(v) } })} />
      <Field label="Cross venues (comma list)" value={Array.isArray(draft.paper?.cross_venues) ? draft.paper.cross_venues.join(',') : (draft.paper?.cross_venues || '')}
        onChange={v => setDraft({ ...draft, paper: { ...draft.paper, cross_venues: v.split(',').map(s => s.trim()).filter(Boolean) } })} />
      <button onClick={() => save('paper', draft.paper)} disabled={loading}>Save paper config</button>
    </div>

    <h2>Exchange API keys</h2>
    <div style={{ background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 8, padding: 16, marginBottom: 18 }}>
      {Object.keys(exchanges).length ? (
        <table style={{ width: '100%', marginBottom: 12, fontSize: 13 }}>
          <thead><tr><th>Venue</th><th>Has key</th><th>Testnet</th><th></th></tr></thead>
          <tbody>
            {Object.entries(exchanges).map(([v, meta]) => (
              <tr key={v}>
                <td>{v}</td>
                <td>{meta.has_key ? 'yes' : 'no'}</td>
                <td>{meta.testnet ? 'yes' : 'no'}</td>
                <td><button onClick={() => removeExchange(v)}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <Empty what="exchange keys" />}
      <h3 style={{ fontSize: 14, margin: '12px 0 8px' }}>Add exchange key</h3>
      <form onSubmit={addExchange}>
        <Field label="Venue" value={venue} onChange={setVenue} required />
        <Field label="API key" value={apiKey} onChange={setApiKey} required />
        <Field label="API secret" value={secret} onChange={setSecret} required />
        <Toggle label="Testnet" checked={testnet} onChange={setTestnet} />
        <Toggle label="Withdraw permission (blocked by default)" checked={withdraw} onChange={setWithdraw} />
        <button type="submit" disabled={loading || !apiKey || !secret}>Add encrypted key</button>
      </form>
    </div>

    <h2>Training data</h2>
    <div style={{ background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 8, padding: 16, marginBottom: 18 }}>
      <Field label="Symbols (comma separated)" value={draft.training?.symbols}
        onChange={v => setDraft({ ...draft, training: { ...draft.training, symbols: v } })} />
      <Field label="Timeframe" value={draft.training?.timeframe}
        onChange={v => setDraft({ ...draft, training: { ...draft.training, timeframe: v } })} />
      <Field label="Months of history" type="number" value={draft.training?.months}
        onChange={v => setDraft({ ...draft, training: { ...draft.training, months: Number(v) } })} />
      <p className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
        Set parameters here, then run from the shell:
        <br /><code>python -m scripts.download_history --symbol {draft.training?.symbols?.split(',')[0] || 'BTC/USDT'} --timeframe {draft.training?.timeframe || '1h'} --months {draft.training?.months || 12}</code>
        <br /><code>python -m scripts.train_from_history --parquet --exchange binance --symbol {draft.training?.symbols?.split(',')[0] || 'BTC/USDT'} --timeframe {draft.training?.timeframe || '1h'}</code>
      </p>
      <button onClick={() => save('training', draft.training)} disabled={loading}>Save training settings</button>
    </div>

    <h2>Effective config preview</h2>
    <pre className="muted" style={{ fontSize: 12, maxHeight: 300, overflow: 'auto' }}>{JSON.stringify(settings, null, 2)}</pre>
  </div>
}

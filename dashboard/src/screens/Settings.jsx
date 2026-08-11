import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth.jsx'
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Empty,
  Input,
  Label,
  Select,
  Switch,
  Table,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Tile,
} from '../components/ui'

const FEATURES = [
  ['live_data', 'Live market data (disable for offline paper)'],
  ['scalp_enabled', 'Scalp strategy'],
  ['cross_exchange_enabled', 'Cross-exchange arbitrage'],
  ['multi_venue_live', 'Multi-venue live execution (gated)'],
  ['streaming_enabled', 'Streaming websockets'],
  ['telegram_enabled', 'Telegram notifications'],
  ['llm_news_sensor', 'LLM news sensor'],
]

function FormItem({ label, children, hint }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

export default function Settings() {
  const { user } = useAuth()
  const [settings, setSettings] = useState(null)
  const [draft, setDraft] = useState({})
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')

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

  const notify = (msg, error = false) => {
    setMessage({ text: msg, error })
    setTimeout(() => setMessage(''), 4000)
  }

  const save = async (section, payload) => {
    setLoading(true)
    const res = await api.patchSettingsConfig({ [section]: payload })
    setLoading(false)
    if (res) {
      notify(`${section} saved`)
      await load()
    } else {
      notify(`Failed to save ${section}`, true)
    }
  }

  const addExchange = async (e) => {
    e.preventDefault()
    setLoading(true)
    const res = await api.addExchange({ venue, apiKey, secret, testnet, withdraw, exchange_id: venue })
    setLoading(false)
    if (res) {
      notify(`Added ${venue} key`)
      setApiKey('')
      setSecret('')
      await load()
    } else {
      notify('Failed to add exchange key', true)
    }
  }

  const removeExchange = async (v) => {
    setLoading(true)
    const res = await api.deleteExchange(v)
    setLoading(false)
    if (res) {
      notify(`Removed ${v}`)
      await load()
    } else {
      notify('Failed to remove exchange key', true)
    }
  }

  if (!settings || !draft.mode) {
    return (
      <div className="page">
        <h1>Settings</h1>
        <p className="text-muted-foreground">Loading…</p>
      </div>
    )
  }

  const exchanges = settings.exchanges || {}
  const updateSection = (section, patch) => setDraft(d => {
    const current = d[section]
    if (current && typeof current === 'object' && !Array.isArray(current)) {
      return { ...d, [section]: { ...current, ...patch } }
    }
    const firstValue = Object.values(patch)[0]
    return { ...d, [section]: firstValue }
  })

  const formatValue = (v) => {
    if (v === null || v === undefined) return '—'
    if (Array.isArray(v)) return v.join(', ') || '—'
    if (typeof v === 'boolean') return v ? 'true' : 'false'
    if (typeof v === 'object') {
      return (
        <dl className="space-y-0.5 pl-2 border-l border-border">
          {Object.entries(v).map(([kk, vv]) => (
            <div key={kk} className="flex justify-between gap-2">
              <dt className="text-muted-foreground">{kk}</dt>
              <dd className="truncate font-mono">{formatValue(vv)}</dd>
            </div>
          ))}
        </dl>
      )
    }
    return String(v)
  }

  return (
    <div className="page animate-fade-in">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1>Settings</h1>
          <p className="text-sm text-muted-foreground">
            Single-user trading configuration. Changes are persisted and reloaded at runtime boot.
          </p>
        </div>
        {message && (
          <Badge dir={message.error ? 'down' : 'up'}>{message.text}</Badge>
        )}
      </div>

      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Tile k="User" v={user?.username || user?.id || '—'} />
        <Tile k="Mode" v={draft.mode || 'paper'} />
        <Tile k="Configured exchanges" v={Object.keys(exchanges).length} />
      </div>

      <Tabs defaultValue="mode" className="space-y-6">
        <TabsList>
          <TabsTrigger value="mode">Mode & Features</TabsTrigger>
          <TabsTrigger value="mandate">Mandate</TabsTrigger>
          <TabsTrigger value="paper">Paper</TabsTrigger>
          <TabsTrigger value="exchanges">Exchanges</TabsTrigger>
          <TabsTrigger value="training">Training</TabsTrigger>
          <TabsTrigger value="preview">Effective config</TabsTrigger>
        </TabsList>

        <TabsContent value="mode" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Trading mode</CardTitle>
              <CardDescription>Paper simulates trades; live requires the go-live ladder.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <FormItem label="Mode" hint="Live mode stays fail-closed until mandate and ladder are satisfied.">
                <Select
                  value={draft.mode}
                  onValueChange={(v) => updateSection('mode', { mode: v })}
                  options={[
                    { value: 'paper', label: 'Paper trading' },
                    { value: 'live', label: 'Live trading' },
                  ]}
                />
              </FormItem>
              <Button onClick={() => save('mode', draft.mode)} disabled={loading}>
                Save mode
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Features</CardTitle>
              <CardDescription>Safe keyless toggles can also be flipped at runtime in Controls.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                {FEATURES.map(([key, label]) => (
                  <div key={key} className="flex items-center justify-between rounded-md border p-3">
                    <Label htmlFor={key} className="cursor-pointer">{label}</Label>
                    <Switch
                      id={key}
                      checked={!!draft.features?.[key]}
                      onCheckedChange={(v) => updateSection('features', { [key]: v })}
                    />
                  </div>
                ))}
              </div>
              <div className="mt-4">
                <Button onClick={() => save('features', draft.features)} disabled={loading}>
                  Save features
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="mandate" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Mandate (go-live guard)</CardTitle>
              <CardDescription>Hard limits enforced by the execution layer before any live order.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between rounded-md border p-3">
                <Label htmlFor="mandate-enabled" className="cursor-pointer">Enable mandate (required before live/testnet)</Label>
                <Switch
                  id="mandate-enabled"
                  checked={!!draft.mandate?.enabled}
                  onCheckedChange={(v) => updateSection('mandate', { enabled: v })}
                />
              </div>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <FormItem label="Max total notional (USDT)">
                  <Input
                    type="number"
                    value={draft.mandate?.max_total_notional_usdt || ''}
                    onChange={(e) => updateSection('mandate', { max_total_notional_usdt: Number(e.target.value) })}
                  />
                </FormItem>
                <FormItem label="Max positions">
                  <Input
                    type="number"
                    value={draft.mandate?.max_positions || ''}
                    onChange={(e) => updateSection('mandate', { max_positions: Number(e.target.value) })}
                  />
                </FormItem>
                <FormItem label="Max risk % per trade">
                  <Input
                    type="number"
                    value={draft.mandate?.max_risk_pct_per_trade || ''}
                    onChange={(e) => updateSection('mandate', { max_risk_pct_per_trade: Number(e.target.value) })}
                  />
                </FormItem>
              </div>
              <Button onClick={() => save('mandate', draft.mandate)} disabled={loading}>
                Save mandate
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="paper" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Paper config</CardTitle>
              <CardDescription>Simulation parameters used by the paper broker.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <FormItem label="Starting equity (USDT)">
                  <Input
                    type="number"
                    value={draft.paper?.starting_equity_usdt || ''}
                    onChange={(e) => updateSection('paper', { starting_equity_usdt: Number(e.target.value) })}
                  />
                </FormItem>
                <FormItem label="Max symbols">
                  <Input
                    type="number"
                    value={draft.paper?.max_symbols || ''}
                    onChange={(e) => updateSection('paper', { max_symbols: Number(e.target.value) })}
                  />
                </FormItem>
                <FormItem label="Data venue">
                  <Input
                    value={draft.paper?.data_exchange || ''}
                    onChange={(e) => updateSection('paper', { data_exchange: e.target.value })}
                  />
                </FormItem>
              </div>
              <FormItem label="Cross venues (comma separated)" hint="Venues to watch for cross-exchange arbitrage.">
                <Input
                  value={Array.isArray(draft.paper?.cross_venues) ? draft.paper.cross_venues.join(', ') : (draft.paper?.cross_venues || '')}
                  onChange={(e) => updateSection('paper', { cross_venues: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })}
                />
              </FormItem>
              <Button onClick={() => save('paper', draft.paper)} disabled={loading}>
                Save paper config
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="exchanges" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Exchange API keys</CardTitle>
              <CardDescription>Keys are encrypted at rest and never returned to the UI.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {Object.keys(exchanges).length ? (
                <Table
                  cols={['Venue', 'Has key', 'Testnet', { label: 'Action', align: 'right' }]}
                  rows={Object.entries(exchanges).map(([v, meta]) => [
                    <span className="font-medium" key="v">{v}</span>,
                    <Badge key="has" dir={meta.has_key ? 'up' : 'down'}>{meta.has_key ? 'yes' : 'no'}</Badge>,
                    <Badge key="test" dir={meta.testnet ? 'up' : 'down'}>{meta.testnet ? 'yes' : 'no'}</Badge>,
                    <div key="act" className="text-right">
                      <Button variant="outline" size="sm" onClick={() => removeExchange(v)} disabled={loading}>
                        Remove
                      </Button>
                    </div>,
                  ])}
                />
              ) : (
                <Empty what="exchange keys" />
              )}

              <div className="rounded-lg border p-4">
                <h3 className="mb-3 text-sm font-semibold">Add exchange key</h3>
                <form onSubmit={addExchange} className="space-y-3">
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <FormItem label="Venue">
                      <Input value={venue} onChange={(e) => setVenue(e.target.value)} required />
                    </FormItem>
                    <FormItem label="API key">
                      <Input value={apiKey} onChange={(e) => setApiKey(e.target.value)} required />
                    </FormItem>
                    <FormItem label="API secret">
                      <Input value={secret} onChange={(e) => setSecret(e.target.value)} required />
                    </FormItem>
                  </div>
                  <div className="flex flex-wrap gap-6">
                    <div className="flex items-center space-x-2">
                      <Switch id="testnet" checked={testnet} onCheckedChange={setTestnet} />
                      <Label htmlFor="testnet" className="cursor-pointer">Testnet</Label>
                    </div>
                    <div className="flex items-center space-x-2">
                      <Switch id="withdraw" checked={withdraw} onCheckedChange={setWithdraw} />
                      <Label htmlFor="withdraw" className="cursor-pointer">Withdraw permission</Label>
                    </div>
                  </div>
                  <Button type="submit" disabled={loading || !apiKey || !secret}>
                    Add encrypted key
                  </Button>
                </form>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="training" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Training data</CardTitle>
              <CardDescription>Set symbols and window, then run the CLI commands below.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <FormItem label="Symbols (comma separated)">
                  <Input value={draft.training?.symbols || ''} onChange={(e) => updateSection('training', { symbols: e.target.value })} />
                </FormItem>
                <FormItem label="Timeframe">
                  <Select
                    value={draft.training?.timeframe}
                    onValueChange={(v) => updateSection('training', { timeframe: v })}
                    options={[
                      { value: '1m', label: '1m' },
                      { value: '5m', label: '5m' },
                      { value: '15m', label: '15m' },
                      { value: '1h', label: '1h' },
                      { value: '4h', label: '4h' },
                      { value: '1d', label: '1d' },
                    ]}
                  />
                </FormItem>
                <FormItem label="Months of history">
                  <Input
                    type="number"
                    value={draft.training?.months || ''}
                    onChange={(e) => updateSection('training', { months: Number(e.target.value) })}
                  />
                </FormItem>
              </div>
              <div className="rounded-md bg-muted/30 p-3 text-xs font-mono text-muted-foreground">
                python -m scripts.download_history --symbol {draft.training?.symbols?.split(',')[0] || 'BTC/USDT'} --timeframe {draft.training?.timeframe || '1h'} --months {draft.training?.months || 12}
                <br />
                python -m scripts.train_from_history --parquet --exchange binance --symbol {draft.training?.symbols?.split(',')[0] || 'BTC/USDT'} --timeframe {draft.training?.timeframe || '1h'}
              </div>
              <Button onClick={() => save('training', draft.training)} disabled={loading}>
                Save training settings
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="preview" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Effective config preview</CardTitle>
              <CardDescription>Merged config that the runtime will use on next boot.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {Object.entries(settings).filter(([, v]) => v && typeof v === 'object').map(([section, values]) => (
                  <div key={section} className="rounded-md border p-3">
                    <h4 className="mb-2 text-sm font-semibold capitalize">{section}</h4>
                    <dl className="space-y-1 text-xs">
                      {Object.entries(values).map(([k, v]) => (
                        <div key={k} className="flex justify-between gap-2">
                          <dt className="text-muted-foreground">{k}</dt>
                          <dd className="font-mono">{formatValue(v)}</dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}

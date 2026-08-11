import React, { useState } from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Label, Switch, Table } from '../components/ui'

export default function Controls() {
  const { data } = usePoll(api.features, 4000)
  const [busy, setBusy] = useState(null)
  const feats = data?.features || {}
  const toggleable = data?.toggleable || []
  const locked = data?.locked || {}
  const halted = !!data?.halted

  async function flip(name, next) {
    setBusy(name)
    await api.setFeature(name, next)
    setBusy(null)
  }

  async function doControl(action) {
    setBusy(action)
    await api.control(action, { confirm: 'CONFIRM' })
    setBusy(null)
  }

  return <div className="page animate-fade-in space-y-4">
    <div className="mb-4">
      <h1>Controls</h1>
      <p className="text-sm text-muted-foreground">Toggle safe, keyless features at runtime — they take effect on the next tick, no restart. Live/funded features are locked here and require the §23.8 go-live ladder + funded keys. Also available on Telegram: <code className="font-mono">/features · /enable &lt;name&gt; · /disable &lt;name&gt;</code>.</p>
    </div>

    <Card>
      <CardHeader>
        <CardTitle>Killswitch</CardTitle>
        <CardDescription>Immediately halt or reset all trading.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-4">
        <p className="text-sm text-muted-foreground">
          {halted
            ? 'The system is HALTED. No trades will be placed until reset.'
            : 'The system is running. Trigger a halt to force NO_TRADE across all symbols.'}
        </p>
        {halted
          ? <Button onClick={() => doControl('unhalt')} disabled={busy === 'unhalt'} variant="outline">{busy === 'unhalt' ? '…' : 'Reset halt'}</Button>
          : <Button onClick={() => doControl('killswitch')} disabled={busy === 'killswitch'} variant="destructive">{busy === 'killswitch' ? '…' : 'Halt trading'}</Button>}
        <span className="ml-auto text-sm">Status: <Badge dir={halted ? 'down' : 'up'}>{halted ? 'halted' : 'running'}</Badge></span>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>Runtime-toggleable</CardTitle>
        <CardDescription>Flip these without a restart.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {toggleable.map(name => {
            const on = !!feats[name]
            return (
              <div key={name} className="flex items-center justify-between rounded-md border p-3">
                <div>
                  <Label htmlFor={`feat-${name}`} className="cursor-pointer font-mono text-sm">{name}</Label>
                  <p className="text-xs text-muted-foreground">{on ? 'enabled' : 'disabled'}</p>
                </div>
                <Switch
                  id={`feat-${name}`}
                  checked={on}
                  disabled={busy === name || halted}
                  onCheckedChange={(v) => flip(name, v)}
                />
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>Other flags</CardTitle>
        <CardDescription>Set in config; restart to apply.</CardDescription>
      </CardHeader>
      <CardContent>
        <Table
          cols={['Feature', 'State']}
          rows={['telegram', 'llm_news_sensor', 'live_data'].map(n => [
            <span key={n} className="font-mono">{n}</span>,
            <Badge key={n + 'b'} dir={feats[n] ? 'up' : 'flat'}>{feats[n] ? 'on' : 'off'}</Badge>,
          ])}
        />
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>Locked — require the go-live ladder + capital</CardTitle>
      </CardHeader>
      <CardContent>
        <Table
          cols={['Feature', 'Why locked']}
          rows={Object.entries(locked).map(([name, why]) => [
            <span key={name} className="font-mono">{name}</span>,
            <span key={name + 'why'} className="text-sm text-muted-foreground">{why}</span>,
          ])}
        />
      </CardContent>
    </Card>
  </div>
}

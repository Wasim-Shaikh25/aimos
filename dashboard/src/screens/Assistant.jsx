import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api'

// Read-only AI analyst (§15.3). Ask questions about the running system or generate
// a timeframe report — answered from the journal + metrics. It never trades or
// changes anything; recommendations are advisory (you act via Controls).
const SUGGESTIONS = [
  'How did the last 24h go?',
  'Is the ML working?',
  'Which strategy is working best?',
  'Should we do more paper trading or train more on history?',
  'Any issues you can see in the system right now?',
]

export default function Assistant() {
  const [enabled, setEnabled] = useState(null)
  const [thread, setThread] = useState([])   // {role, text, meta}
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [tf, setTf] = useState('24h')
  const end = useRef(null)

  useEffect(() => { api.assistantStatus().then(s => setEnabled(!!s?.enabled)) }, [])
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }) }, [thread, busy])

  const send = async (q) => {
    const question = (q ?? input).trim()
    if (!question || busy) return
    setInput('')
    setThread(t => [...t, { role: 'you', text: question }])
    setBusy(true)
    const r = await api.ask(question)
    setThread(t => [...t, r?.answer
      ? { role: 'analyst', text: r.answer, meta: r.grounded_on }
      : { role: 'analyst', text: '⚠️ analyst unavailable (enable it + set ANTHROPIC_API_KEY).' }])
    setBusy(false)
  }

  const genReport = async () => {
    if (busy) return
    setThread(t => [...t, { role: 'you', text: `Generate a report for the last ${tf}` }])
    setBusy(true)
    const r = await api.report(tf)
    setThread(t => [...t, r?.report
      ? { role: 'analyst', text: r.report, meta: r.grounded_on }
      : { role: 'analyst', text: '⚠️ analyst unavailable (enable it + set ANTHROPIC_API_KEY).' }])
    setBusy(false)
  }

  return <div className="page"><h1>AI Analyst</h1>
    <p className="muted">Read-only. Answers from the journal + metrics — it explains and advises,
      it never trades or changes settings (§15.3). Recommendations are yours to act on via Controls.</p>

    {enabled === false && <p className="muted">⚠️ The analyst is <b>disabled</b>. Enable it with
      <code className="mono"> assistant.enabled: true</code> (or <code className="mono">AIMOS__ASSISTANT__ENABLED=true</code>)
      and set <code className="mono">ANTHROPIC_API_KEY</code>, then restart. You can still type below to see the flow.</p>}

    <div className="row" style={{ gap: 8, flexWrap: 'wrap', margin: '8px 0' }}>
      {SUGGESTIONS.map(s => <button key={s} className="chip" onClick={() => send(s)} disabled={busy}>{s}</button>)}
      <span style={{ flex: 1 }} />
      <select value={tf} onChange={e => setTf(e.target.value)} aria-label="Report time window">
        {['1h', '6h', '24h', '7d', '30d'].map(o => <option key={o} value={o}>{o}</option>)}
      </select>
      <button className="chip" onClick={genReport} disabled={busy}>Generate report</button>
    </div>

    <div className="panel" style={{ minHeight: 240, padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
      {thread.length === 0 && <p className="muted">Ask anything about the system, or generate a report.</p>}
      {thread.map((m, i) => (
        <div key={i} style={{ alignSelf: m.role === 'you' ? 'flex-end' : 'flex-start', maxWidth: '85%' }}>
          <div className={`badge ${m.role === 'you' ? 'b-flat' : 'b-up'}`}>{m.role}</div>
          <div style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>{m.text}</div>
          {m.meta && <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
            grounded on {m.meta.decisions ?? 0} decisions
            {m.meta.window ? ` · ${m.meta.window}` : ''}
            {m.meta.monitor_coverage != null ? ` · coverage ${m.meta.monitor_coverage}%` : ''}
          </div>}
        </div>
      ))}
      {busy && <div className="muted">analyst is thinking…</div>}
      <div ref={end} />
    </div>

    <form className="row" style={{ gap: 8, marginTop: 10 }} onSubmit={e => { e.preventDefault(); send() }}>
      <input style={{ flex: 1 }} placeholder="Ask the analyst…" aria-label="Ask the analyst"
        value={input} onChange={e => setInput(e.target.value)} disabled={busy} />
      <button className="chip" type="submit" disabled={busy || !input.trim()}>Ask</button>
    </form>
  </div>
}

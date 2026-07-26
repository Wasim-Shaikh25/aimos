import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { usePoll } from '../hooks'
import CandlestickChart from '../components/CandlestickChart'
import { Empty } from '../components/ui'

export default function Candles() {
  const { data: prices } = usePoll(api.prices, 4000)
  const [base, setBase] = useState('')
  const [venue, setVenue] = useState('')
  const [candles, setCandles] = useState(null)
  const assets = (prices?.rows || []).map(r => r.base).sort()

  useEffect(() => {
    if (!base) { setCandles(null); return }
    api.candles(base).then(d => {
      setCandles(d)
      const vs = d?.venues || []
      if (vs.length && (!venue || !vs.includes(venue))) setVenue(vs[0])
    })
  }, [base])

  const data = candles?.candles?.[venue] || []

  return <div className="page"><h1>Candlestick chart</h1>
    <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 12 }}>
      <label className="muted">Asset&nbsp;
        <select value={base} onChange={e => setBase(e.target.value)}>
          <option value="">select…</option>
          {assets.map(a => <option key={a} value={a}>{a}</option>)}
        </select>
      </label>
      {candles?.venues?.length > 0 && <label className="muted">Venue&nbsp;
        <select value={venue} onChange={e => setVenue(e.target.value)}>
          {candles.venues.map(v => <option key={v} value={v}>{v}</option>)}
        </select>
      </label>}
    </div>
    {data.length > 0 ? <CandlestickChart data={data} /> : <Empty what="candle data" />}
  </div>
}

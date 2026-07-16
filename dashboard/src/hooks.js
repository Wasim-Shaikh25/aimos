import { useEffect, useRef, useState } from 'react'

// Live polling — re-fetches every `ms` so the UI reflects the running loop
// (the backend ticks every paper.loop_seconds; the UI refreshes independently).
// Returns { data, updatedAt } where updatedAt is the last successful fetch time.
export function usePoll(fn, ms = 4000, deps = []) {
  const [data, setData] = useState(undefined)
  const [updatedAt, setUpdatedAt] = useState(null)
  const saved = useRef(fn)
  saved.current = fn
  useEffect(() => {
    let alive = true
    const run = () => saved.current().then(d => {
      if (!alive) return
      if (d !== null && d !== undefined) { setData(d); setUpdatedAt(Date.now()) }
      else if (data === undefined) setData(null)
    })
    run()
    const id = setInterval(run, ms)
    return () => { alive = false; clearInterval(id) }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  return { data, updatedAt }
}

// "3s ago" style relative label for the live indicator.
export function ago(ts) {
  if (!ts) return '—'
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000))
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  return `${m}m ${s % 60}s ago`
}

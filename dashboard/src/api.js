// Journal-backed API client (§15.1). All screens read these — what you see is
// exactly what the pipeline journaled (§16.2).
const j = async (url, opts) => {
  try {
    const r = await fetch(url, opts)
    if (!r.ok) throw new Error(r.status)
    return await r.json()
  } catch (e) { return null }
}
export const api = {
  decisions: (n = 50) => j(`/api/decisions?limit=${n}`),
  state: (sym) => j(`/api/state/${sym}`),
  anatomy: (id) => j(`/api/decision/${id}/anatomy`),
  positions: () => j('/api/positions'),
  equity: () => j('/api/equity'),
  stats: () => j('/api/journal/stats'),
  markets: () => j('/api/markets'),
  matrix: () => j('/api/universe/matrix'),
  evidence: (sym) => j(`/api/evidence/${sym}`),
  strategies: () => j('/api/strategies'),
  models: () => j('/api/models'),
  config: () => j('/api/config/effective'),
  agents: () => j('/api/agents'),
  proposals: () => j('/api/proposals'),
  control: (action, body) => j(`/api/control/${action}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
  }),
}

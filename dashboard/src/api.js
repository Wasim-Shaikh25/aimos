// Journal-backed API client (§15.1) + SaaS auth helpers.
// Access token is kept in memory; refresh token is an httpOnly cookie.
let accessToken = ''
let activeOrg = localStorage.getItem('aimos_org') || ''

const authHeaders = () => {
  const h = { 'Content-Type': 'application/json' }
  if (accessToken) h.Authorization = `Bearer ${accessToken}`
  if (activeOrg) h['X-Organization-Id'] = activeOrg
  return h
}

const j = async (url, opts = {}) => {
  try {
    const r = await fetch(url, { ...opts, headers: { ...authHeaders(), ...(opts.headers || {}) } })
    if (r.status === 401) {
      // Propagate auth failures so the UI can clear tokens and show login.
      const err = new Error(`Unauthorized`)
      err.status = 401
      throw err
    }
    if (!r.ok) throw new Error(r.status)
    if (r.status === 204) return null
    return await r.json()
  } catch (e) {
    if (e.status === 401) throw e
    return null
  }
}

export const setAuth = ({ access_token, organization_id }) => {
  if (access_token) accessToken = access_token
  if (organization_id) {
    activeOrg = organization_id
    localStorage.setItem('aimos_org', organization_id)
  }
}

export const clearAuth = () => {
  accessToken = ''
  activeOrg = ''
  localStorage.removeItem('aimos_org')
}

export const getAuth = () => ({
  accessToken,
  activeOrg,
})

export const api = {
  // SaaS auth (single admin, email OTP 2FA)
  login: (email, password) => j('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  verifyLogin: (email, code) => j('/auth/login/verify', { method: 'POST', body: JSON.stringify({ email, code }) }),
  logout: () => j('/auth/logout', { method: 'POST' }),
  refresh: () => j('/auth/refresh', { method: 'POST' }),
  me: () => j('/api/v2/me'),

  // Single-user settings (config + encrypted exchange secrets)
  settings: () => j('/api/v2/settings'),
  patchSettingsConfig: (overrides) => j('/api/v2/settings/config', { method: 'PATCH', body: JSON.stringify({ overrides }) }),
  addExchange: (data) => j('/api/v2/settings/exchange', { method: 'POST', body: JSON.stringify(data) }),
  deleteExchange: (venue) => j(`/api/v2/settings/exchange/${venue}`, { method: 'DELETE' }),
  changePassword: (current_password, new_password) => j('/api/v2/me/password', {
    method: 'POST', body: JSON.stringify({ current_password, new_password }),
  }),

  // Runtime
  decisions: (n = 50) => j(`/api/decisions?limit=${n}`),
  state: (sym) => j(`/api/state/${sym}`),
  anatomy: (id) => j(`/api/decision/${id}/anatomy`),
  graph: (id) => j(`/api/decision/${id}/graph`),
  positions: () => j('/api/positions'),
  equity: () => j('/api/equity'),
  stats: () => j('/api/journal/stats'),
  markets: () => j('/api/markets'),
  matrix: () => j('/api/universe/matrix'),
  evidence: (sym, venue) => j(`/api/evidence/${sym}${venue ? `?venue=${venue}` : ''}`),
  prices: () => j('/api/prices/matrix'),
  candles: (sym) => j(`/api/candles/${sym}`),
  venueState: (sym) => j(`/api/venue_state/${sym}`),
  trades: () => j('/api/trades'),
  balances: () => j('/api/balances'),
  performance: () => j('/api/performance'),
  connections: () => j('/api/connections'),
  features: () => j('/api/features'),
  setFeature: (name, enabled) => j('/api/control/feature', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm: 'CONFIRM', name, enabled }),
  }),
  golive: () => j('/api/golive'),
  monitor: () => j('/api/monitor'),
  risk: () => j('/api/risk'),
  assistantStatus: () => j('/api/assistant'),
  ask: (question) => j('/api/assistant', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  }),
  report: (timeframe) => j(`/api/assistant/report?timeframe=${encodeURIComponent(timeframe || '24h')}`),
  debate: (decision_id) => j(`/api/assistant/debate/${encodeURIComponent(decision_id)}`),
  setGolive: (gate, passed) => j('/api/control/golive', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm: 'CONFIRM', gate, passed }),
  }),
  strategies: () => j('/api/strategies'),
  models: () => j('/api/models'),
  config: () => j('/api/config/effective'),
  agents: () => j('/api/agents'),
  proposals: () => j('/api/proposals'),
  control: (action, body) => j(`/api/control/${action}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
  }),
}

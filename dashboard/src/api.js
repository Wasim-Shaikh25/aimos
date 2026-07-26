// Journal-backed API client (§15.1) + SaaS auth helpers.
// Auth tokens and active organization are persisted in localStorage and sent
// as the Authorization / X-Organization-Id headers on every request.
const authHeaders = () => {
  const h = { 'Content-Type': 'application/json' }
  const token = localStorage.getItem('aimos_access_token')
  const org = localStorage.getItem('aimos_active_org')
  if (token) h.Authorization = `Bearer ${token}`
  if (org) h['X-Organization-Id'] = org
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

export const setAuth = ({ access_token, refresh_token, organization_id }) => {
  if (access_token) localStorage.setItem('aimos_access_token', access_token)
  if (refresh_token) localStorage.setItem('aimos_refresh_token', refresh_token)
  if (organization_id) localStorage.setItem('aimos_active_org', organization_id)
}

export const clearAuth = () => {
  localStorage.removeItem('aimos_access_token')
  localStorage.removeItem('aimos_refresh_token')
  localStorage.removeItem('aimos_active_org')
}

export const getAuth = () => ({
  accessToken: localStorage.getItem('aimos_access_token'),
  refreshToken: localStorage.getItem('aimos_refresh_token'),
  activeOrg: localStorage.getItem('aimos_active_org'),
})

export const api = {
  // SaaS auth
  register: (email, password) => j('/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) }),
  login: (email, password) => j('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  logout: () => {
    const refresh = localStorage.getItem('aimos_refresh_token')
    return j('/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token: refresh || '' }) })
  },
  refresh: () => {
    const refresh = localStorage.getItem('aimos_refresh_token')
    return j('/auth/refresh', { method: 'POST', body: JSON.stringify({ refresh_token: refresh || '' }) })
  },
  verifyEmail: (email, code) => j('/auth/verify-email', { method: 'POST', body: JSON.stringify({ email, code }) }),
  resendVerification: (email) => j('/auth/resend-verification', { method: 'POST', body: JSON.stringify({ email }) }),
  forgotPassword: (email) => j('/auth/forgot-password', { method: 'POST', body: JSON.stringify({ email }) }),
  resetPassword: (email, code, new_password) => j('/auth/reset-password', {
    method: 'POST', body: JSON.stringify({ email, code, new_password }),
  }),
  sendPhoneCode: (phone_number) => j('/auth/phone/send', { method: 'POST', body: JSON.stringify({ phone_number }) }),
  verifyPhone: (phone_number, code) => j('/auth/phone/verify', {
    method: 'POST', body: JSON.stringify({ phone_number, code }),
  }),
  me: () => j('/api/v2/me'),
  organizations: () => j('/api/v2/organizations'),
  createOrganization: (name) => j('/api/v2/organizations?name=' + encodeURIComponent(name), { method: 'POST' }),
  orgConfig: () => j('/api/v2/config'),
  setOrgConfig: (overrides) => j('/api/v2/config', { method: 'PATCH', body: JSON.stringify(overrides) }),
  members: (orgId) => j(`/api/v2/organizations/${orgId}/members`),
  inviteMember: (orgId, email, role = 'member') => j(`/api/v2/organizations/${orgId}/invite`, {
    method: 'POST', body: JSON.stringify({ email, role }),
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
  assistantStatus: () => j('/api/assistant'),
  ask: (question) => j('/api/assistant', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  }),
  report: (timeframe) => j(`/api/assistant/report?timeframe=${encodeURIComponent(timeframe || '24h')}`),
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

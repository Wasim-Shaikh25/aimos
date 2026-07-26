import React, { createContext, useContext, useEffect, useState } from 'react'
import { api, setAuth, clearAuth, getAuth } from './api.js'

const AuthContext = createContext(null)
const LOCAL_USER = { id: 'local', email: 'single-user' }
const LOCAL_ORG = { id: 'local', name: 'Local', slug: 'local', role: 'owner', mode: 'paper' }

export const useAuth = () => useContext(AuthContext)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [organizations, setOrganizations] = useState([])
  const [activeOrg, setActiveOrg] = useState(localStorage.getItem('aimos_active_org') || null)
  const [saasEnabled, setSaasEnabled] = useState(false)
  const [loading, setLoading] = useState(true)

  const chooseOrg = (orgId) => {
    localStorage.setItem('aimos_active_org', orgId)
    setActiveOrg(orgId)
  }

  const clearSession = () => {
    clearAuth()
    setUser(null)
    setOrganizations([])
    setActiveOrg(null)
  }

  const loadSession = async () => {
    const { accessToken } = getAuth()
    if (!accessToken) { setLoading(false); return }
    try {
      const me = await api.me()
      if (!me) { throw new Error('Unauthorized') }
      setUser(me)
      const orgs = await api.organizations()
      setOrganizations(orgs || [])
      if (orgs?.length && !activeOrg) chooseOrg(orgs[0].id)
    } catch (e) {
      if (e.status === 401 || e.message === 'Unauthorized') clearSession()
    } finally {
      setLoading(false)
    }
  }

  const init = async () => {
    try {
      const status = await fetch('/api/v2/status').then(r => r.ok ? r.json() : null)
      const enabled = status?.saas_enabled ?? false
      setSaasEnabled(enabled)
      if (!enabled) {
        // Non-SaaS deployments skip the login screen and use a local tenant.
        setUser(LOCAL_USER)
        setOrganizations([LOCAL_ORG])
        chooseOrg(LOCAL_ORG.id)
        setLoading(false)
        return
      }
    } catch {
      // If the status endpoint is unavailable, fall through to auth flow.
    }
    await loadSession()
  }

  const handleTokens = (data) => {
    setAuth(data)
    chooseOrg(data.organization_id)
  }

  const login = async (email, password) => {
    const data = await api.login(email, password)
    if (!data) return null
    handleTokens(data)
    await loadSession()
    return data
  }

  const register = async (email, password) => {
    const data = await api.register(email, password)
    if (!data) return null
    handleTokens(data)
    await loadSession()
    return data
  }

  const logout = async () => {
    if (saasEnabled) await api.logout()
    clearSession()
  }

  const verifyEmail = async (email, code) => {
    const res = await api.verifyEmail(email, code)
    if (res) await loadSession()
    return res
  }

  const resendVerification = (email) => api.resendVerification(email)

  useEffect(() => { init() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const value = {
    user, setUser,
    organizations, setOrganizations,
    activeOrg, chooseOrg,
    saasEnabled,
    loading,
    login, register, logout,
    verifyEmail, resendVerification,
    loadSession,
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

function Field({ label, type = 'text', value, onChange, required = true }) {
  return (
    <label style={{ display: 'block', marginBottom: 12 }}>
      <span style={{ display: 'block', color: 'var(--muted)', fontSize: 12, marginBottom: 4 }}>{label}</span>
      <input type={type} value={value} onChange={e => onChange(e.target.value)} required={required}
        style={{ width: '100%', padding: '8px 10px', background: '#222836', color: 'var(--text)', border: '1px solid var(--line)', borderRadius: 6 }} />
    </label>
  )
}

export function LoginScreen() {
  const { login, register, verifyEmail, resendVerification } = useAuth()
  const [mode, setMode] = useState('login') // login | register | verify
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')

  const submit = async (e) => {
    e.preventDefault(); setError(''); setOk('')
    try {
      if (mode === 'login') {
        const data = await login(email, password)
        if (!data) setError('Invalid email or password')
      } else if (mode === 'register') {
        const data = await register(email, password)
        if (!data) setError('Registration failed')
        else setMode('verify')
      } else {
        const res = await verifyEmail(email, code)
        if (res?.email_verified) setOk('Email verified — reload to continue')
        else setError('Invalid or expired code')
      }
    } catch (e) {
      setError(e.message || 'Request failed')
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
      <div style={{ width: 360, padding: 24, background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 12 }}>
        <h1 style={{ margin: '0 0 18px', fontSize: 20 }}>AIMOS</h1>
        {mode !== 'verify' && <p style={{ color: 'var(--muted)', margin: '0 0 18px' }}>
          {mode === 'login' ? 'Sign in to your account' : 'Create a free account'}
        </p>}
        {mode === 'verify' && <p style={{ color: 'var(--muted)', margin: '0 0 18px' }}>Enter the verification code sent to {email}</p>}
        <form onSubmit={submit}>
          <Field label="Email" type="email" value={email} onChange={setEmail} />
          {mode !== 'verify' && <Field label="Password" type="password" value={password} onChange={setPassword} />}
          {mode === 'verify' && <Field label="Verification code" value={code} onChange={setCode} />}
          {error && <p style={{ color: 'var(--red)', fontSize: 13 }}>{error}</p>}
          {ok && <p style={{ color: 'var(--green)', fontSize: 13 }}>{ok}</p>}
          <button type="submit" style={{ width: '100%', marginTop: 8, padding: '10px' }}>
            {mode === 'login' ? 'Sign in' : mode === 'register' ? 'Create account' : 'Verify email'}
          </button>
        </form>
        <div style={{ marginTop: 14, color: 'var(--muted)', fontSize: 13, display: 'flex', justifyContent: 'space-between' }}>
          {mode === 'login' ? (
            <a href="#" onClick={e => { e.preventDefault(); setMode('register') }}>Create account</a>
          ) : mode === 'register' ? (
            <a href="#" onClick={e => { e.preventDefault(); setMode('login') }}>Already have an account?</a>
          ) : (
            <a href="#" onClick={async e => { e.preventDefault(); await resendVerification(email); setOk('Code resent') }}>Resend code</a>
          )}
          {mode === 'verify' && <a href="#" onClick={e => { e.preventDefault(); setMode('login') }}>Sign in instead</a>}
        </div>
      </div>
    </div>
  )
}

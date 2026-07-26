import React, { createContext, useContext, useEffect, useState } from 'react'
import { api, setAuth, clearAuth, getAuth } from './api.js'

const AuthContext = createContext(null)
const LOCAL_USER = { id: 'local', email: 'single-user' }

export const useAuth = () => useContext(AuthContext)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [saasEnabled, setSaasEnabled] = useState(false)
  const [loading, setLoading] = useState(true)

  const clearSession = () => {
    clearAuth()
    setUser(null)
  }

  const loadSession = async () => {
    const { accessToken } = getAuth()
    if (!accessToken) { setLoading(false); return }
    try {
      const me = await api.me()
      if (!me) { throw new Error('Unauthorized') }
      setUser(me)
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
        setUser(LOCAL_USER)
        setLoading(false)
        return
      }
    } catch {
      // If the status endpoint is unavailable, fall through to auth flow.
    }
    await loadSession()
  }

  const login = async (email, password) => {
    return await api.login(email, password)
  }

  const verifyLogin = async (email, code) => {
    const data = await api.verifyLogin(email, code)
    if (!data) return null
    setAuth(data)
    await loadSession()
    return data
  }

  const logout = async () => {
    if (saasEnabled) await api.logout()
    clearSession()
  }

  useEffect(() => { init() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const value = {
    user, setUser,
    saasEnabled,
    loading,
    login, verifyLogin, logout,
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
  const { login, verifyLogin } = useAuth()
  const [mode, setMode] = useState('login') // login | verify
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')

  const submit = async (e) => {
    e.preventDefault(); setError(''); setOk('')
    try {
      if (mode === 'login') {
        const res = await login(email, password)
        if (res?.ok) {
          setOk(res.message || 'Check your email for the login code')
          setMode('verify')
        } else {
          setError('Invalid email or password')
        }
      } else {
        const data = await verifyLogin(email, code)
        if (!data) setError('Invalid or expired code')
      }
    } catch (e) {
      setError(e.message || 'Request failed')
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
      <div style={{ width: 360, padding: 24, background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 12 }}>
        <h1 style={{ margin: '0 0 18px', fontSize: 20 }}>AIMOS</h1>
        <p style={{ color: 'var(--muted)', margin: '0 0 18px' }}>
          {mode === 'login' ? 'Sign in to your account' : `Enter the login code sent to ${email}`}
        </p>
        <form onSubmit={submit}>
          {mode === 'login' && (
            <>
              <Field label="Email" type="email" value={email} onChange={setEmail} />
              <Field label="Password" type="password" value={password} onChange={setPassword} />
            </>
          )}
          {mode === 'verify' && (
            <Field label="Login code" value={code} onChange={setCode} />
          )}
          {error && <p style={{ color: 'var(--red)', fontSize: 13 }}>{error}</p>}
          {ok && <p style={{ color: 'var(--green)', fontSize: 13 }}>{ok}</p>}
          <button type="submit" style={{ width: '100%', marginTop: 8, padding: '10px' }}>
            {mode === 'login' ? 'Send login code' : 'Verify and sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}

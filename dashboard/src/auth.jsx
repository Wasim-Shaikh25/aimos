import React, { createContext, useContext, useEffect, useState } from 'react'
import { api, setAuth, clearAuth, getAuth } from './api.js'

const AuthContext = createContext(null)

export const useAuth = () => useContext(AuthContext)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  const clearSession = () => {
    clearAuth()
    setUser(null)
  }

  const loadSession = async () => {
    try {
      let { accessToken } = getAuth()
      if (!accessToken) {
        const data = await api.refresh()
        if (!data) { throw new Error('Unauthorized') }
        setAuth(data)
        accessToken = data.access_token
      }
      const me = await api.me()
      if (!me) { throw new Error('Unauthorized') }
      setUser(me)
    } catch (e) {
      if (e.status === 401 || e.message === 'Unauthorized') clearSession()
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadSession() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const login = async (username, password) => {
    const data = await api.login(username, password)
    if (!data || !data.access_token) return null
    setAuth(data)
    await loadSession()
    return data
  }

  const logout = async () => {
    await api.logout()
    clearSession()
  }

  const value = { user, setUser, loading, login, logout, loadSession }
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
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  const submit = async (e) => {
    e.preventDefault(); setError('')
    try {
      const data = await login(username, password)
      if (!data) setError('Invalid username or password')
    } catch (e) {
      setError(e.message || 'Request failed')
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
      <div style={{ width: 360, padding: 24, background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 12 }}>
        <h1 style={{ margin: '0 0 18px', fontSize: 20 }}>AIMOS</h1>
        <p style={{ color: 'var(--muted)', margin: '0 0 18px' }}>Sign in to your account</p>
        <form onSubmit={submit}>
          <Field label="Username" value={username} onChange={setUsername} />
          <Field label="Password" type="password" value={password} onChange={setPassword} />
          {error && <p style={{ color: 'var(--red)', fontSize: 13 }}>{error}</p>}
          <button type="submit" style={{ width: '100%', marginTop: 8, padding: '10px' }}>Sign in</button>
        </form>
      </div>
    </div>
  )
}

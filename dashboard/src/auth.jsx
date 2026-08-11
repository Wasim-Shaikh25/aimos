import React, { createContext, useContext, useEffect, useState } from 'react'
import { api, setAuth, clearAuth, getAuth } from './api.js'
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Label } from './components/ui'

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
    <div className="min-h-screen flex items-center justify-center bg-background animate-fade-in">
      <Card className="w-full max-w-sm shadow-xl border-border">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl">AIMOS</CardTitle>
          <CardDescription>Sign in with your admin credentials</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <Input id="username" value={username} onChange={e => setUsername(e.target.value)} required />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" value={password} onChange={e => setPassword(e.target.value)} required />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full">Sign in</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}

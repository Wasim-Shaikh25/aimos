import React, { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { api } from './api'
import { usePoll, ago } from './hooks'
import { AuthProvider, useAuth, LoginScreen } from './auth.jsx'
import Markets from './screens/Markets.jsx'
import AssetDetail from './screens/AssetDetail.jsx'
import DecisionAnatomy from './screens/DecisionAnatomy.jsx'
import UniverseMatrix from './screens/UniverseMatrix.jsx'
import PositionsRisk from './screens/PositionsRisk.jsx'
import Decisions from './screens/Decisions.jsx'
import Performance from './screens/Performance.jsx'
import ConfigViewer from './screens/ConfigViewer.jsx'
import Agents from './screens/Agents.jsx'
import Engines from './screens/Engines.jsx'
import Strategies from './screens/Strategies.jsx'
import Models from './screens/Models.jsx'
import Prices from './screens/Prices.jsx'
import Candles from './screens/Candles.jsx'
import Trades from './screens/Trades.jsx'
import Balances from './screens/Balances.jsx'
import MindMap from './screens/MindMap.jsx'
import Connections from './screens/Connections.jsx'
import Controls from './screens/Controls.jsx'
import GoLive from './screens/GoLive.jsx'
import Monitor from './screens/Monitor.jsx'
import Assistant from './screens/Assistant.jsx'
import Settings from './screens/Settings.jsx'

const NAV = [
  ['/', 'Markets'], ['/prices', 'Prices'], ['/candles', 'Candles'], ['/anatomy', 'Decision Anatomy'], ['/mindmap', 'Mind-map'],
  ['/engines', 'Engines'], ['/strategies', 'Strategies'], ['/models', 'Models'], ['/universe', 'Universe'],
  ['/positions', 'Positions & Risk'], ['/trades', 'Trade History'], ['/balances', 'Balances'],
  ['/connections', 'Connections'], ['/controls', 'Controls'], ['/golive', 'Go-Live'],
  ['/monitor', 'Monitor'], ['/assistant', 'AI Analyst'], ['/decisions', 'Decisions'],
  ['/performance', 'Performance'], ['/config', 'Config'], ['/agents', 'Agents'],
  ['/settings', 'Settings'],
]

function Chrome() {
  const { user, logout } = useAuth()
  const { data: stats, updatedAt } = usePoll(api.stats, 4000)
  const { data: eq } = usePoll(api.equity, 4000)
  const [, tick] = useState(0)
  useEffect(() => { const id = setInterval(() => tick(t => t + 1), 1000); return () => clearInterval(id) }, [])
  const equity = eq?.equity?.length ? eq.equity[eq.equity.length - 1] : 10000
  if (!user) return null
  return (
    <div className="chrome">
      <span className="stat">Equity <b>${Number(equity).toFixed(0)}</b></span>
      <span className="stat">Decisions <b>{stats?.n_decisions ?? '—'}</b></span>
      <span className="stat">NO_TRADE rate <b>{stats ? (stats.no_trade_rate * 100).toFixed(0) + '%' : '—'}</b></span>
      <span className="stat">Mode <b className="b-flat badge">paper</b></span>
      <span className="stat live"><i className="dot" /> live · <b>{ago(updatedAt)}</b></span>
      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center' }}>
        <span className="stat" style={{ marginRight: 12 }}>{user?.username || user?.id}</span>
        <button onClick={logout}>Logout</button>
      </div>
    </div>
  )
}

function Dashboard() {
  return (
    <>
      <Chrome />
      <nav className="side">
        {NAV.map(([p, l]) => <NavLink key={p} to={p} className={({ isActive }) => isActive ? 'active' : ''}>{l}</NavLink>)}
      </nav>
      <Routes>
        <Route path="/" element={<Markets />} />
        <Route path="/prices" element={<Prices />} />
        <Route path="/candles" element={<Candles />} />
        <Route path="/asset/:base" element={<AssetDetail />} />
        <Route path="/anatomy" element={<DecisionAnatomy />} />
        <Route path="/mindmap" element={<MindMap />} />
        <Route path="/engines" element={<Engines />} />
        <Route path="/strategies" element={<Strategies />} />
        <Route path="/models" element={<Models />} />
        <Route path="/universe" element={<UniverseMatrix />} />
        <Route path="/positions" element={<PositionsRisk />} />
        <Route path="/trades" element={<Trades />} />
        <Route path="/balances" element={<Balances />} />
        <Route path="/connections" element={<Connections />} />
        <Route path="/controls" element={<Controls />} />
        <Route path="/golive" element={<GoLive />} />
        <Route path="/monitor" element={<Monitor />} />
        <Route path="/assistant" element={<Assistant />} />
        <Route path="/decisions" element={<Decisions />} />
        <Route path="/performance" element={<Performance />} />
        <Route path="/config" element={<ConfigViewer />} />
        <Route path="/agents" element={<Agents />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </>
  )
}

function Router() {
  const { loading, user } = useAuth()
  if (loading) return <div style={{ padding: 40, color: 'var(--muted)' }}>Loading…</div>
  return user ? <Dashboard /> : <LoginScreen />
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Router />
      </BrowserRouter>
    </AuthProvider>
  )
}

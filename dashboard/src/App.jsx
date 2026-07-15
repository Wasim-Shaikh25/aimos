import React, { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { api } from './api'
import Markets from './screens/Markets.jsx'
import AssetDetail from './screens/AssetDetail.jsx'
import DecisionAnatomy from './screens/DecisionAnatomy.jsx'
import UniverseMatrix from './screens/UniverseMatrix.jsx'
import PositionsRisk from './screens/PositionsRisk.jsx'
import Decisions from './screens/Decisions.jsx'
import Performance from './screens/Performance.jsx'
import ConfigViewer from './screens/ConfigViewer.jsx'
import Agents from './screens/Agents.jsx'

const NAV = [
  ['/', 'Markets'], ['/anatomy', 'Decision Anatomy'], ['/universe', 'Universe'],
  ['/positions', 'Positions & Risk'], ['/decisions', 'Decisions'],
  ['/performance', 'Performance'], ['/config', 'Config'], ['/agents', 'Agents'],
]

function Chrome() {
  const [stats, setStats] = useState(null)
  const [eq, setEq] = useState(null)
  useEffect(() => { api.stats().then(setStats); api.equity().then(setEq) }, [])
  const equity = eq?.equity?.length ? eq.equity[eq.equity.length - 1] : 10000
  return (
    <div className="chrome">
      <span className="stat">Equity <b>${Number(equity).toFixed(0)}</b></span>
      <span className="stat">Decisions <b>{stats?.n_decisions ?? '—'}</b></span>
      <span className="stat">NO_TRADE rate <b>{stats ? (stats.no_trade_rate * 100).toFixed(0) + '%' : '—'}</b></span>
      <span className="stat">Mode <b className="b-flat badge">paper</b></span>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Chrome />
      <nav className="side">
        {NAV.map(([p, l]) => <NavLink key={p} to={p} className={({ isActive }) => isActive ? 'active' : ''}>{l}</NavLink>)}
      </nav>
      <Routes>
        <Route path="/" element={<Markets />} />
        <Route path="/asset/:base" element={<AssetDetail />} />
        <Route path="/anatomy" element={<DecisionAnatomy />} />
        <Route path="/universe" element={<UniverseMatrix />} />
        <Route path="/positions" element={<PositionsRisk />} />
        <Route path="/decisions" element={<Decisions />} />
        <Route path="/performance" element={<Performance />} />
        <Route path="/config" element={<ConfigViewer />} />
        <Route path="/agents" element={<Agents />} />
      </Routes>
    </BrowserRouter>
  )
}

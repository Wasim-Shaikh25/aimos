import React, { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { api } from './api'
import { usePoll, ago } from './hooks'
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
import Trades from './screens/Trades.jsx'
import Balances from './screens/Balances.jsx'
import MindMap from './screens/MindMap.jsx'

const NAV = [
  ['/', 'Markets'], ['/prices', 'Prices'], ['/anatomy', 'Decision Anatomy'], ['/mindmap', 'Mind-map'],
  ['/engines', 'Engines'], ['/strategies', 'Strategies'], ['/models', 'Models'], ['/universe', 'Universe'],
  ['/positions', 'Positions & Risk'], ['/trades', 'Trade History'], ['/balances', 'Balances'],
  ['/decisions', 'Decisions'], ['/performance', 'Performance'], ['/config', 'Config'], ['/agents', 'Agents'],
]

function Chrome() {
  const { data: stats, updatedAt } = usePoll(api.stats, 4000)
  const { data: eq } = usePoll(api.equity, 4000)
  const [, tick] = useState(0)
  useEffect(() => { const id = setInterval(() => tick(t => t + 1), 1000); return () => clearInterval(id) }, [])
  const equity = eq?.equity?.length ? eq.equity[eq.equity.length - 1] : 10000
  return (
    <div className="chrome">
      <span className="stat">Equity <b>${Number(equity).toFixed(0)}</b></span>
      <span className="stat">Decisions <b>{stats?.n_decisions ?? '—'}</b></span>
      <span className="stat">NO_TRADE rate <b>{stats ? (stats.no_trade_rate * 100).toFixed(0) + '%' : '—'}</b></span>
      <span className="stat">Mode <b className="b-flat badge">paper</b></span>
      <span className="stat live"><i className="dot" /> live · <b>{ago(updatedAt)}</b></span>
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
        <Route path="/prices" element={<Prices />} />
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
        <Route path="/decisions" element={<Decisions />} />
        <Route path="/performance" element={<Performance />} />
        <Route path="/config" element={<ConfigViewer />} />
        <Route path="/agents" element={<Agents />} />
      </Routes>
    </BrowserRouter>
  )
}

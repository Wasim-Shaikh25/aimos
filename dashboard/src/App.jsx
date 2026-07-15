import React from 'react'
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
// The 8+1 screens from §16.2 / §18.5.
import Markets from './screens/Markets.jsx'
import AssetDetail from './screens/AssetDetail.jsx'
import DecisionAnatomy from './screens/DecisionAnatomy.jsx'
import UniverseMatrix from './screens/UniverseMatrix.jsx'
import PositionsRisk from './screens/PositionsRisk.jsx'
import Decisions from './screens/Decisions.jsx'
import Performance from './screens/Performance.jsx'
import ConfigViewer from './screens/ConfigViewer.jsx'
import Agents from './screens/Agents.jsx'

const SCREENS = [
  ['/', 'Markets', Markets],
  ['/asset/:base', 'Asset', AssetDetail],
  ['/anatomy', 'Decision Anatomy', DecisionAnatomy],
  ['/universe', 'Universe & Venues', UniverseMatrix],
  ['/positions', 'Positions & Risk', PositionsRisk],
  ['/decisions', 'Decisions', Decisions],
  ['/performance', 'Performance', Performance],
  ['/config', 'Config', ConfigViewer],
  ['/agents', 'Agents', Agents],
]

export default function App() {
  return (
    <BrowserRouter>
      <nav style={{ display: 'flex', gap: 12, padding: 8, borderBottom: '1px solid #ccc' }}>
        {SCREENS.filter(([p]) => !p.includes(':')).map(([path, label]) => (
          <NavLink key={path} to={path}>{label}</NavLink>
        ))}
      </nav>
      <Routes>
        {SCREENS.map(([path, , C]) => <Route key={path} path={path} element={<C />} />)}
      </Routes>
    </BrowserRouter>
  )
}

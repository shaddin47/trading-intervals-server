import React from 'react'
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { AppProvider } from '@/hooks/useApp'
import { GanttPage } from '@/pages/GanttPage'
import { ConfigPage } from '@/pages/ConfigPage'
import './index.css'

function Layout() {
  return (
    <div className="app">
      <nav className="nav-tabs">
        <NavLink
          to="/"
          end
          className={({ isActive }) => `nav-tab${isActive ? ' active' : ''}`}
        >
          Timeline
        </NavLink>
        <NavLink
          to="/config"
          className={({ isActive }) => `nav-tab${isActive ? ' active' : ''}`}
        >
          Config
        </NavLink>
      </nav>
      <Routes>
        <Route path="/"       element={<GanttPage />} />
        <Route path="/config" element={<ConfigPage />} />
      </Routes>
    </div>
  )
}

export default function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <Layout />
      </BrowserRouter>
    </AppProvider>
  )
}

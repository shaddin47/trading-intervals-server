import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, NavLink, useLocation } from 'react-router-dom'
import { AppProvider, useApp } from '@/hooks/useApp'
import { GanttPage } from '@/pages/GanttPage'
import { ConfigPage } from '@/pages/ConfigPage'
import './index.css'

function Layout() {
  const { configUnlocked, setConfigUnlocked } = useApp()
  const location = useLocation()

  // Unlock permanently the first time the user visits /config
  useEffect(() => {
    if (!configUnlocked && location.pathname === '/config') {
      setConfigUnlocked(true)
    }
  }, [location.pathname, configUnlocked, setConfigUnlocked])

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
        {configUnlocked && (
          <NavLink
            to="/config"
            className={({ isActive }) => `nav-tab${isActive ? ' active' : ''}`}
          >
            Config
          </NavLink>
        )}
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

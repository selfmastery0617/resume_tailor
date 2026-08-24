import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './print.css'
import App from './App.tsx'
import { PrintPage } from './print/PrintPage.tsx'
import { initTheme } from './components/ThemeToggle.tsx'

// The PDF generator loads /print?token=... . Routing on pathname avoids adding
// a router dependency, and keeps the print view completely free of app chrome.
const isPrintRoute = window.location.pathname.replace(/\/+$/, '') === '/print'

if (isPrintRoute) {
  document.documentElement.setAttribute('data-print', 'true')
  // Deliberately skip the theme: a resume is printed on white paper, so the
  // print route must never inherit the user's dark-mode choice.
} else {
  initTheme()
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>{isPrintRoute ? <PrintPage /> : <App />}</StrictMode>,
)

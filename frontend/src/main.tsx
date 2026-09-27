import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { AccessApp } from './components/AccessApp.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AccessApp />
  </StrictMode>,
)

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import Plain from './Plain.tsx'

// Entry for the single-file build: the plain variant only.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Plain />
  </StrictMode>,
)

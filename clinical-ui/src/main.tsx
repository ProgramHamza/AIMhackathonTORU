import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import Plain from './Plain.tsx'

// /normal serves the plain, minimal variant; everything else serves the paper design.
const plain = window.location.pathname.replace(/\/+$/, '') === '/normal'

createRoot(document.getElementById('root')!).render(<StrictMode>{plain ? <Plain /> : <App />}</StrictMode>)

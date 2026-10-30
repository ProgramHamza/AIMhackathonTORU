import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/dm-sans';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import './index.css';
import App from './App';
import { datasets } from './data/dataset';
import { validateRefs } from './lib/sources';

if (import.meta.env.DEV) datasets.forEach((d) => validateRefs(d.encounter, d.store));

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// /api goes to the Python backend (backend/app/server.py); override with BACKEND_URL.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { '/api': process.env.BACKEND_URL ?? 'http://127.0.0.1:8000' },
  },
});

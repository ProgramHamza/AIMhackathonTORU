import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { viteSingleFile } from 'vite-plugin-singlefile'

// Builds the plain variant into one self-contained HTML file: `npm run build:single`
export default defineConfig({
  plugins: [react(), tailwindcss(), viteSingleFile()],
  build: {
    outDir: 'dist-single',
    emptyOutDir: true,
    rollupOptions: { input: 'plain.html' },
  },
})

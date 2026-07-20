import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base '/' — absolute asset URLs (/assets/…). Required for clean-URL routing:
// a relative base would resolve assets against deep paths like /<slug>/papers/…
// and 404. `reref web` serves dist/ at the domain root, so '/' is correct.
// The dev server proxies /api to the Python backend so there's no CORS in dev.
export default defineConfig({
  plugins: [react()],
  base: '/',
  build: { outDir: 'dist', emptyOutDir: true },
  server: { proxy: { '/api': 'http://127.0.0.1:8765' } },
})

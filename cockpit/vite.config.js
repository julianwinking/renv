import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base './' so the built bundle works when served by `reref web` from cockpit/dist.
// The dev server proxies /api to the Python backend so there's no CORS in dev.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: { outDir: 'dist', emptyOutDir: true },
  server: { proxy: { '/api': 'http://127.0.0.1:8765' } },
})

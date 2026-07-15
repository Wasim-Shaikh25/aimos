import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
// Dev proxy to the FastAPI backend (§15.1); never expose publicly (§23.4).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000', '/ws': { target: 'ws://127.0.0.1:8000', ws: true } } }
})

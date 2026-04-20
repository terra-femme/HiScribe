import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/session': { target: 'http://localhost:3000', ws: true },
      '/health':  { target: 'http://localhost:3000' }
    }
  }
})

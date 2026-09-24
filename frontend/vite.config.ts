import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Browser calls /api on the same origin as Vite.
// Vite forwards those requests to the backend container.
// This removes CORS/preflight from the data-source connection flow.
export default defineConfig({
  plugins: [react()],

  server: {
    proxy: {
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
      },
    },
  },
})


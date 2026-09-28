import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: process.env.VITE_BASE_PATH || '/',
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('@supabase')) return 'supabase'
        },
      },
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: process.env.BACKEND_URL || 'http://127.0.0.1:8000', changeOrigin: true },
      '/ready': { target: process.env.BACKEND_URL || 'http://127.0.0.1:8000' },
    },
  },
})

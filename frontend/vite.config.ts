import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/stream': {
        target: process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/simulate': {
        target: process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/auth': {
        target: process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom'],
          charts: ['chart.js', 'react-chartjs-2'],
          query: ['@tanstack/react-query'],
        },
      },
    },
  },
})

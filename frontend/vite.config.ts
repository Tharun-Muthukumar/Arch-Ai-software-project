import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  optimizeDeps: mode === 'test' ? undefined : {
    // Mermaid loads each diagram renderer dynamically. Pre-bundle the complete
    // client dependency set up front so its chunk URLs cannot be invalidated by
    // Vite's incremental dependency discovery after the first page has loaded.
    noDiscovery: true,
    include: [
      '@tanstack/react-query',
      'clsx',
      'lucide-react',
      'mermaid',
      'react',
      'react-dom/client',
      'react-markdown',
      'react-router-dom',
      'reactflow',
      'recharts',
      'remark-gfm',
    ],
  },
  build: {
    chunkSizeWarningLimit: 3200,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/mermaid')) {
            return 'mermaid'
          }
          if (id.includes('node_modules/reactflow')) {
            return 'diagrams'
          }
          if (id.includes('node_modules/recharts')) {
            return 'charts'
          }
          if (
            id.includes('node_modules/react-markdown') ||
            id.includes('node_modules/remark-gfm')
          ) {
            return 'markdown'
          }
          return undefined
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
    pool: 'threads',
  },
}))

import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [],
  server: {
    host: '0.0.0.0',
    port: 5174,
    proxy: {
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
      '/state': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // NOTE: /assets is NOT proxied — it serves static sprites from public/assets/.
      // The asset registry API is available at /api/assets instead.
      '/api/assets': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path: string) => path.replace('/api/assets', '/assets'),
      },
      '/agent': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/world': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/simulation': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      }
    }
  }
});

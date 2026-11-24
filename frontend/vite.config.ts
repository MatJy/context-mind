import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Keep browser requests on the frontend origin; FastAPI needs no CORS changes.
const proxy = { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true, timeout: 0 } };

export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy },
  preview: { host: '127.0.0.1', proxy },
  test: { environment: 'jsdom', setupFiles: './src/test-setup.ts', clearMocks: true },
});

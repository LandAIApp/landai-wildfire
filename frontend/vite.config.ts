/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// VITE_BASE_PATH is only needed for GitHub Pages project sites (e.g. /landai-wildfire/).
export default defineConfig({
  base: process.env.VITE_BASE_PATH || '/',
  plugins: [react()],
  server: { port: 5173, host: true },
  // Most tests render to strings (node); interaction tests opt in to jsdom with `// @vitest-environment jsdom`.
  test: { environment: 'node', globals: false, css: false },
});

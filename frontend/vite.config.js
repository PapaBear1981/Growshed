import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  build: {
    // Conservative targets: the wall display is an old tablet (see docs/ARCHITECTURE.md §5).
    target: 'es2018',
    cssTarget: 'chrome61',
  },
  server: {
    // `npm run dev` talks to a backend running on localhost:8000.
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
});

import { defineConfig } from 'vite';

export default defineConfig(({ mode }) => ({
  base: './',
  worker: { format: 'es' },
  build: { target: 'es2022', outDir: mode === 'dashboard' ? 'dist-local' : 'dist',
    ...(mode === 'dashboard' ? { rolldownOptions: { input: ['index.html', 'dashboard.html'] } } : {}) },
}));

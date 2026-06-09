import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'
import tailwindcss from '@tailwindcss/vite'

import path from 'node:path';

export default defineConfig(({ command }) => {
  const isDev = command === 'serve';

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: Number(process.env.PORT ?? 4000),
      allowedHosts: [
        'localhost',
        '127.0.0.1',
        'trendpulse.local',
        'frontend',
      ],
      // HMR для локальной разработки без nginx.
      // В production-стеке (make up) фронтенд отдаётся SSR-сервером за nginx.
      hmr: {
        protocol: 'ws',
        clientPort: Number(process.env.PORT ?? 4000),
        path: '/__vite_hmr',
      },
      ...isDev ? { host: true } : {},
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    build: {
      rollupOptions: {
        external: (id) => {
          const normalizedId = id.replace(/\\/g, '/');
          return (
            normalizedId.includes('/server/') ||
            normalizedId.startsWith('../server/') ||
            normalizedId.startsWith('./server/') ||
            normalizedId.includes('server/client')
          );
        },
      },
    },
    ssr: {
      external: [
        'server',
        '../server',
        './server',
        'server/client',
        'server/ssr',
        '../server/client',
        './server/client',
      ],
      noExternal: [],
    },
  }
})

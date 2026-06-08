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
        'app.postbridge.local',
        'api.postbridge.local',
        'storage.postbridge.local',
        'postbridge-frontend',
      ],
      // HMR проксируется через nginx по /__vite_hmr → postbridge-frontend:24678.
      // host НЕ задаём: bind возьмётся из server.host (true → 0.0.0.0), а
      // браузер использует location.hostname (=app.postbridge.local).
      // clientPort: 443 — браузер ходит через TLS-терминатор; port: 24678 —
      // dedicated WS-сервер Vite (минует Fastify catch-all).
      hmr: {
        protocol: 'wss',
        clientPort: 443,
        path: '/__vite_hmr',
        port: 24678,
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

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
      // SSR server reads dist/client/index.html (prodIndexHtmlPath in ssr.factory.ts)
      // and serves static assets from dist/client/.
      outDir: 'dist/client',
      rollupOptions: {
        // Exclude server-side code from the client bundle.
        // The server/ directory is executed by Node (tsx/fastify) and must NOT
        // be bundled into the browser assets — it imports node-only modules
        // (fastify, axios, fs, etc.) that are not available in the browser.
        external: (id) => {
          const normalizedId = id.replace(/\\/g, '/');
          return (
            normalizedId.includes('/server/') ||
            normalizedId.startsWith('../server/') ||
            normalizedId.startsWith('./server/') ||
            normalizedId.includes('server/client')
          );
        },
        output: {
          // vendor-split manualChunks — eliminates the 729kB monolithic chunk
          // warning by splitting vendor deps into separate cacheable chunks.
          //
          // IMPORTANT: react + react-dom MUST stay in the SAME chunk to prevent
          // the "react singleton" problem where two different React instances
          // coexist (breaks hooks). Do NOT split react from react-dom.
          manualChunks(id) {
            const normalizedId = id.replace(/\\/g, '/');

            // react + react-dom → vendor-react (singleton, must be one chunk)
            if (
              normalizedId.includes('/node_modules/react/') ||
              normalizedId.includes('/node_modules/react-dom/') ||
              normalizedId.includes('/node_modules/react-error-boundary/') ||
              normalizedId.includes('/node_modules/scheduler/')
            ) {
              return 'vendor-react';
            }

            // @tanstack/* → vendor-tanstack
            if (normalizedId.includes('/node_modules/@tanstack/')) {
              return 'vendor-tanstack';
            }

            // @radix-ui/* + clsx + class-variance-authority + tailwind-merge
            // + lucide-react → vendor-ui
            if (
              normalizedId.includes('/node_modules/@radix-ui/') ||
              normalizedId.includes('/node_modules/clsx/') ||
              normalizedId.includes('/node_modules/class-variance-authority/') ||
              normalizedId.includes('/node_modules/tailwind-merge/') ||
              normalizedId.includes('/node_modules/lucide-react/')
            ) {
              return 'vendor-ui';
            }

            // react-hook-form + @hookform → vendor-forms
            if (
              normalizedId.includes('/node_modules/react-hook-form/') ||
              normalizedId.includes('/node_modules/@hookform/')
            ) {
              return 'vendor-forms';
            }
          },
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

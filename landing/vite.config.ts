import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';

export default defineConfig(({ command }) => {
  const isDev = command === 'serve';

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: Number(process.env.PORT ?? 5174),
      allowedHosts: [
        'postbridge.local',
        'postbridge-landing',
      ],
      hmr: {
        protocol: 'wss',
        clientPort: 443,
      },
      ...isDev ? { host: true } : {},
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    build: {
      outDir: 'dist/client',
    },
  }
});

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // listen on 0.0.0.0 so the container port is reachable
    port: Number(process.env.WEB_PORT ?? 5173),
    watch: {
      // bind-mounted source over WSL: polling keeps HMR reliable in-container
      usePolling: true,
    },
    // 开发期 /api 代理到本地 wrangler dev（Worker），前端保持同源调用。
    proxy: {
      '/api': {
        target: 'http://localhost:8787',
        changeOrigin: true,
      },
    },
  },
});

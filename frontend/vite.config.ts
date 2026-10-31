import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import Inspector from 'unplugin-vue-dev-locator/vite'

// https://vite.dev/config/
export default defineConfig({
  build: {
    sourcemap: 'hidden',
  },
  plugins: [vue(), Inspector()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'), // ✅ 定义 @ = src
    },
  },
  // 前端开发服务器配置
  server: {
    port: 8011, // Vue启动端口
    host: '0.0.0.0', // 允许 FRP 转发到开发服务器
    proxy: {
      '/chat': 'http://127.0.0.1:8000',
      '/conversations': 'http://127.0.0.1:8000',
      '/documents': 'http://127.0.0.1:8000',
      '/upload': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/evaluation': 'http://127.0.0.1:8000',
      '/obsidian': 'http://127.0.0.1:8000',
    },
  },
})

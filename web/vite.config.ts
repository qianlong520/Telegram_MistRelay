import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    host: '0.0.0.0', // 监听所有网络接口，允许外部访问
    port: 5173,
    allowedHosts: [
      'oracle-us-1.jiuyue520.com',
      'localhost',
      '.jiuyue520.com' // 允许所有 jiuyue520.com 的子域名
    ],
    // HMR配置：增加超时时间，避免热重载超时
    hmr: {
      timeout: 60000, // 60秒超时（默认10秒）
      overlay: true // 显示错误覆盖层
    },
    // 文件监听配置：优化性能，排除不必要的文件
    watch: {
      ignored: [
        '**/node_modules/**',
        '**/.git/**',
        '**/dist/**',
        '**/build/**',
        '**/*.md'
      ],
      usePolling: false, // 在ARM设备上可能需要设置为true
      interval: 100 // 轮询间隔（ms），仅在usePolling为true时有效
    },
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        secure: false,
        timeout: 30000 // 代理请求超时时间
      }
    }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vue-vendor': ['vue', 'vue-router', 'pinia'],
          'ui-vendor': ['element-plus'],
          'utils-vendor': ['@vueuse/core', 'axios']
        }
      }
    }
  }
})

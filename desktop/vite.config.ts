import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 1420,
    strictPort: true,
    watch: {ignored: ['**/.test-data/**','**/src-tauri/target/**','**/src-tauri/gen/**','**/test-results/**','**/playwright-report/**']},
  },
  clearScreen: false,
})

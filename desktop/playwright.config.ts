import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: 'tests/e2e',
  use: { baseURL: 'http://127.0.0.1:1420', viewport: { width: 1440, height: 880 } },
  webServer: { command: 'npm run dev', url: 'http://127.0.0.1:1420', reuseExistingServer: false },
  workers: 1,
  retries: 0,
  reporter: 'list',
})

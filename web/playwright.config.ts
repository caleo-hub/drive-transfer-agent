import { defineConfig } from '@playwright/test';
import path from 'node:path';

export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:8767', browserName: 'chromium', trace: 'retain-on-failure' },
  webServer: {
    command: 'uv run --project .. drive-transfer-agent --no-browser',
    url: 'http://127.0.0.1:8767/api/health',
    reuseExistingServer: !process.env.CI,
    env: { DTA_PORT: '8767', DTA_DATA_DIR: path.resolve('../.state/e2e') },
    timeout: 60000,
  },
});

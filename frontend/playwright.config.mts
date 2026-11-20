import { defineConfig } from '@playwright/test';

const port = 5177;
const baseURL = `http://127.0.0.1:${port}`;
const executablePath = process.env.FINEX_CHROMIUM_PATH;

export default defineConfig({
  testDir: './e2e',
  outputDir: '../.runtime/react-browser-results',
  use: {
    baseURL,
    browserName: 'chromium',
    launchOptions: { executablePath },
  },
  webServer: {
    command: `npm run build && npm run preview -- --port ${port} --strictPort`,
    url: `${baseURL}/react-preview/`,
  },
});

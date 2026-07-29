// Playwright config for wealthtax-agent browser E2E smoke tests.
//
// SURFACE: https://wealth.vikenparikh.com — a Streamlit app deployed behind a
// Cloudflare-Access-style ACCESS GATE. A plain, unauthenticated browser request
// will typically land on the access edge / login page, NOT the Streamlit app
// itself. The smoke tests are therefore deliberately robust to the gate: they
// assert that the edge / app-shell RENDERS a real, non-error page — they do NOT
// assert app-internal specifics that only appear once authenticated.
//
// PAPER / READ-ONLY: these tests only navigate and read. They never click a
// login/submit button, never post a form, never write anything, and never
// commit or reference secrets.
//
// LOCAL RUN:
//   cd e2e
//   npm install
//   npx playwright install chromium   # only needed on a bare machine (the CI
//                                      # container image already bundles browsers)
//   npx playwright test
//
// ENV VARS:
//   BASE_URL                   override the target (default below)
//   E2E_ACCESS_BYPASS_COOKIE   optional "name=value" access-bypass cookie for a
//                              gated environment; OFF by default (see smoke.spec.ts)
//   CI                         set by CI; enables retries

import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  retries: process.env.CI ? 2 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.BASE_URL || 'https://wealth.vikenparikh.com',
    ignoreHTTPSErrors: false,
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});

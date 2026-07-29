// Read-only browser smoke tests for wealthtax-agent's deployed surface.
//
// PAPER / READ-ONLY: these tests only navigate and read the rendered page.
// They never click login/submit, never post a form, never write anything, and
// never reference or commit secrets.
//
// ACCESS-GATED SURFACE: https://wealth.vikenparikh.com is a Streamlit app behind
// a Cloudflare-Access-style gate. An unauthenticated hit usually lands on the
// access edge / login page rather than the app. So these tests assert the
// edge / app-shell renders a real, non-error page — NOT app-internal specifics.
//
// ENV VARS:
//   BASE_URL                   target host (default set in playwright.config.ts)
//   E2E_ACCESS_BYPASS_COOKIE   optional "name=value" access-bypass cookie. When
//                              set, an extra test attempts to assert the Streamlit
//                              shell renders. OFF by default (test is skipped).
//                              Never hardcode a cookie/secret — supply via env.

import { test, expect, type ConsoleMessage } from '@playwright/test';

// Benign console-error noise from a third-party access edge / analytics that we
// don't want to fail the smoke on. Kept narrow and documented so a reviewer can
// see exactly what's tolerated. Everything else is treated as a real error.
const BENIGN_CONSOLE = /favicon|analytics|third-party|net::ERR_BLOCKED_BY_CLIENT/i;

test.describe('deployed surface smoke (read-only)', () => {
  test('edge/app shell renders', async ({ page }) => {
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];

    // Register listeners BEFORE navigation so nothing is missed.
    page.on('console', (msg: ConsoleMessage) => {
      if (msg.type() === 'error' && !BENIGN_CONSOLE.test(msg.text())) {
        consoleErrors.push(msg.text());
      }
    });
    page.on('pageerror', (err) => {
      pageErrors.push(err.message);
    });

    const resp = await page.goto('/', { waitUntil: 'domcontentloaded' });

    // The access edge must be UP (not a 5xx / null). A gated edge legitimately
    // returns 401/403 (Cloudflare Access), which is the edge *responding* — that
    // should pass a smoke, not fail it. So assert < 500 (edge alive), not < 400.
    expect(resp, 'expected a navigation response').not.toBeNull();
    expect(
      resp!.status(),
      `expected the edge to be up (status < 500), got ${resp!.status()}`,
    ).toBeLessThan(500);

    // Body must have non-trivial content and the document must have a title.
    await expect(page.locator('body')).not.toBeEmpty();
    const title = await page.title();
    expect(title.trim().length, 'expected a non-empty document title').toBeGreaterThan(0);

    // No console errors and no uncaught page errors (benign noise filtered above).
    expect(
      consoleErrors,
      `unexpected console errors:\n${consoleErrors.join('\n')}`,
    ).toEqual([]);
    expect(
      pageErrors,
      `unexpected page (uncaught) errors:\n${pageErrors.join('\n')}`,
    ).toEqual([]);
  });

  test('read-only reload is stable', async ({ page }) => {
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];

    page.on('console', (msg: ConsoleMessage) => {
      if (msg.type() === 'error' && !BENIGN_CONSOLE.test(msg.text())) {
        consoleErrors.push(msg.text());
      }
    });
    page.on('pageerror', (err) => {
      pageErrors.push(err.message);
    });

    await page.goto('/', { waitUntil: 'domcontentloaded' });

    // Second, read-only load of the same page. No clicks, no writes.
    const resp = await page.goto('/', { waitUntil: 'domcontentloaded' });
    expect(resp, 'expected a navigation response on reload').not.toBeNull();
    expect(resp!.status(), `expected the edge to be up (status < 500), got ${resp!.status()}`).toBeLessThan(500);

    await expect(page.locator('body')).not.toBeEmpty();
    const title = await page.title();
    expect(title.trim().length, 'expected a non-empty title on reload').toBeGreaterThan(0);

    expect(
      consoleErrors,
      `unexpected console errors on reload:\n${consoleErrors.join('\n')}`,
    ).toEqual([]);
    expect(
      pageErrors,
      `unexpected page errors on reload:\n${pageErrors.join('\n')}`,
    ).toEqual([]);
  });

  // OPTIONAL, OFF BY DEFAULT: only runs when E2E_ACCESS_BYPASS_COOKIE is set
  // (format "name=value"). With a valid bypass cookie the access gate is passed
  // and we can assert the actual Streamlit shell renders. Never hardcode the
  // cookie — it must come from the environment.
  test('streamlit shell renders behind access bypass', async ({ context, page }) => {
    test.skip(
      !process.env.E2E_ACCESS_BYPASS_COOKIE,
      'E2E_ACCESS_BYPASS_COOKIE not set — access-gated shell assertion skipped',
    );

    const raw = process.env.E2E_ACCESS_BYPASS_COOKIE!;
    const eq = raw.indexOf('=');
    expect(eq, 'E2E_ACCESS_BYPASS_COOKIE must be "name=value"').toBeGreaterThan(0);
    const name = raw.slice(0, eq).trim();
    const value = raw.slice(eq + 1).trim();

    const base = new URL(process.env.BASE_URL || 'https://wealth.vikenparikh.com');
    await context.addCookies([
      { name, value, domain: base.hostname, path: '/', secure: true, httpOnly: false },
    ]);

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('[data-testid="stApp"], .stApp')).toBeVisible();
  });
});

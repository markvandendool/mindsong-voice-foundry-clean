/**
 * Browser E2E: Voice Foundry integration proof
 *
 * Requirements (Commander audit 2026-04-28):
 * 1. Start Foundry in RC posture with token.
 * 2. Start juke-hub.
 * 3. Open Control Booth / Rocky voice UI.
 * 4. Trigger Rocky speak.
 * 5. Confirm request includes X-Voice-Foundry-Token.
 * 6. Confirm browser CSP allows 127.0.0.1:8788.
 * 7. Confirm audio plays after user gesture.
 * 8. Kill Foundry mid-request.
 * 9. Confirm fallback provider speaks.
 * 10. Confirm no double-speak.
 * 11. Confirm object URL is revoked after playback.
 * 12. Confirm UI returns to idle.
 *
 * Status: SCAFFOLD — requires Playwright + live Foundry + live juke-hub dev server.
 */

import { test, expect } from '@playwright/test';

const FOUNDRY_BASE = 'http://127.0.0.1:8788';
const JUKE_HUB_BASE = 'http://localhost:5173';
const FOUNDRY_TOKEN = process.env.VITE_VOICE_FOUNDRY_TOKEN || 'test-token';

test.describe('Voice Foundry Browser E2E', () => {
  test.beforeEach(async ({ page }) => {
    // Intercept and log all network requests to Foundry
    page.on('request', (req) => {
      if (req.url().includes(':8788')) {
        console.log('[E2E] Foundry request:', req.method(), req.url());
        const headers = req.headers();
        expect(headers['x-voice-foundry-token']).toBeTruthy();
      }
    });

    // Intercept responses for verification
    page.on('response', (res) => {
      if (res.url().includes(':8788')) {
        console.log('[E2E] Foundry response:', res.status(), res.url());
      }
    });
  });

  test('CSP allows Foundry connect-src', async ({ page }) => {
    await page.goto(`${JUKE_HUB_BASE}/control-booth`);

    // Check meta CSP or headers
    const csp = await page.evaluate(() => {
      const meta = document.querySelector('meta[http-equiv="Content-Security-Policy"]');
      return meta?.getAttribute('content') || '';
    });

    expect(csp).toContain('127.0.0.1:8788');
  });

  test('Rocky speak triggers Foundry with token', async ({ page }) => {
    await page.goto(`${JUKE_HUB_BASE}/control-booth`);

    // Wait for Rocky to initialize
    await page.waitForSelector('[data-testid="rocky-status"]', { timeout: 5000 });

    // Click speak button (user gesture required for audio)
    const speakBtn = page.locator('[data-testid="rocky-speak-btn"]').first();
    await speakBtn.click();

    // Wait for Foundry request
    const foundryRequest = page.waitForRequest(
      (req) => req.url().includes('/voice/synthesize') && req.method() === 'POST',
      { timeout: 10000 },
    );

    const req = await foundryRequest;
    const headers = req.headers();
    expect(headers['x-voice-foundry-token']).toBe(FOUNDRY_TOKEN);
  });

  test('Foundry failure falls back to next provider', async ({ page }) => {
    await page.goto(`${JUKE_HUB_BASE}/control-booth`);

    // Simulate Foundry down by blocking the port
    await page.route('http://127.0.0.1:8788/**', (route) => route.abort('failed'));

    const speakBtn = page.locator('[data-testid="rocky-speak-btn"]').first();
    await speakBtn.click();

    // Wait for fallback indicator
    await page.waitForSelector('[data-testid="rocky-fallback-indicator"]', { timeout: 15000 });

    const fallbackText = await page.locator('[data-testid="rocky-fallback-indicator"]').textContent();
    expect(fallbackText).toContain('fallback');
  });

  test('No double-speak after rapid clicks', async ({ page }) => {
    await page.goto(`${JUKE_HUB_BASE}/control-booth`);

    const speakBtn = page.locator('[data-testid="rocky-speak-btn"]').first();

    // Rapid triple-click
    await speakBtn.click();
    await speakBtn.click();
    await speakBtn.click();

    // Count Foundry synthesis requests
    let synthesisCount = 0;
    page.on('request', (req) => {
      if (req.url().includes('/voice/synthesize') && req.method() === 'POST') {
        synthesisCount++;
      }
    });

    await page.waitForTimeout(2000);
    expect(synthesisCount).toBeLessThanOrEqual(1);
  });

  test('UI returns to idle after playback', async ({ page }) => {
    await page.goto(`${JUKE_HUB_BASE}/control-booth`);

    const speakBtn = page.locator('[data-testid="rocky-speak-btn"]').first();
    await speakBtn.click();

    // Wait for speaking state
    await page.waitForSelector('[data-testid="rocky-speaking"]', { timeout: 10000 });

    // Wait for idle state
    await page.waitForSelector('[data-testid="rocky-idle"]', { timeout: 60000 });

    const status = await page.locator('[data-testid="rocky-status"]').textContent();
    expect(status).toContain('idle');
  });
});

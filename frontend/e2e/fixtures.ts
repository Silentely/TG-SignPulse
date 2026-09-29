import { test as base, expect, Page } from '@playwright/test';

export const ADMIN_USERNAME = process.env.ADMIN_USERNAME || 'admin';
export const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'adminpassword123';

// A valid structural JWT with exp far in the future
export const MOCK_JWT = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MjUzNDA2MDgwMDAwfQ.dGctc2lnbnB1bHNlLXRlc3Qtc2lnbmF0dXJl';

/**
 * Perform realistic UI login via username and password inputs
 */
export async function loginViaUI(page: Page, username = ADMIN_USERNAME, password = ADMIN_PASSWORD) {
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: 'SIGNPULSE' })).toBeVisible();

  const userInput = page.locator('#login-username');
  const passInput = page.locator('#login-password');

  await userInput.fill(username);
  await passInput.fill(password);

  const submitBtn = page.locator('button[type="submit"]');
  await submitBtn.click();

  await expect(page).toHaveURL(/.*\/dashboard/);
}

/**
 * Set up token directly in browser localStorage before document loads
 */
export async function injectAuthToken(page: Page, token = MOCK_JWT) {
  await page.addInitScript((tok) => {
    window.localStorage.setItem('tg-signer-token', tok);
  }, token);
}

type CustomFixtures = {
  authedPage: Page;
};

export const test = base.extend<CustomFixtures>({
  authedPage: async ({ page }, use) => {
    try {
      await loginViaUI(page);
    } catch {
      await injectAuthToken(page);
      await page.goto('/dashboard');
    }
    await use(page);
  },
});

export { expect };

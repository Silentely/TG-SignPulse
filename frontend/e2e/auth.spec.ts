import { test, expect, ADMIN_USERNAME, ADMIN_PASSWORD } from './fixtures';

test.describe('Authentication & Access Control', () => {

  test('should redirect unauthenticated users from protected routes to login', async ({ page }) => {
    await test.step('Clear any leftover auth tokens', async () => {
      await page.goto('/login');
      await page.evaluate(() => window.localStorage.clear());
    });

    const protectedPaths = ['/dashboard', '/accounts', '/tasks', '/plugins', '/logs', '/settings'];
    for (const targetPath of protectedPaths) {
      await test.step(`Attempt to access ${targetPath}`, async () => {
        await page.goto(targetPath);
        await expect(page).toHaveURL(/.*\/login/);
      });
    }
  });

  test('should render 404 fallback and navigate back', async ({ page }) => {
    await test.step('Navigate to non-existent route', async () => {
      await page.goto('/some-nonexistent-path-e2e-404');
      await expect(page.getByText('404')).toBeVisible();
    });

    await test.step('Click primary redirect button to return to login or home', async () => {
      const returnBtn = page.getByRole('button', { name: /(前往登录|返回控制台|Go to Login|Back to Home)/i });
      await expect(returnBtn).toBeVisible();
      await returnBtn.click();
      await expect(page).toHaveURL(/.*\/(login|dashboard)/);
    });
  });

  test('should handle login form validation and boundary checks', async ({ page }) => {
    await page.goto('/login');

    const userInput = page.locator('#login-username');
    const passInput = page.locator('#login-password');
    const submitBtn = page.locator('button[type="submit"]');

    await test.step('Password visibility toggle changes input type', async () => {
      await passInput.fill('secret123');
      await expect(passInput).toHaveAttribute('type', 'password');

      const toggleEyeBtn = page.locator('#login-password ~ button');
      await toggleEyeBtn.click();
      await expect(passInput).toHaveAttribute('type', 'text');

      await toggleEyeBtn.click();
      await expect(passInput).toHaveAttribute('type', 'password');
    });

    await test.step('Empty form fields prevent login submission by disabling submit button', async () => {
      await userInput.fill('');
      await passInput.fill('');
      await expect(submitBtn).toBeDisabled();
      await expect(page).toHaveURL(/.*\/login/);
    });
  });

  test('should support dynamic i18n and theme toggle on login screen', async ({ page }) => {
    await page.goto('/login');

    await test.step('Language toggle switches UI text', async () => {
      const langBtn = page.getByRole('button', { name: /(EN|中文)/i });
      if (await langBtn.isVisible()) {
        const prevText = await page.locator('button[type="submit"]').innerText();
        await langBtn.click();
        const newText = await page.locator('button[type="submit"]').innerText();
        expect(newText).not.toEqual(prevText);
      }
    });

    await test.step('Theme toggle modifies document root class', async () => {
      const themeBtn = page.locator('footer button').filter({ has: page.locator('svg') }).first();
      if (await themeBtn.isVisible()) {
        const initialDark = await page.locator('html').evaluate((el) => el.classList.contains('dark'));
        await themeBtn.click();
        const nextDark = await page.locator('html').evaluate((el) => el.classList.contains('dark'));
        expect(nextDark).toBe(!initialDark);
      }
    });
  });

  test('should display alert on invalid login credentials', async ({ page }) => {
    await page.goto('/login');

    await test.step('Submit invalid credentials', async () => {
      await page.locator('#login-username').fill('nonexistent_user');
      await page.locator('#login-password').fill('wrong_password');
      await page.locator('button[type="submit"]').click();
    });

    await test.step('Verify error alert displays and token is not saved', async () => {
      const alert = page.getByRole('alert');
      await expect(alert).toBeVisible();
      await expect(alert).toContainText(/(用户名或密码错误|Invalid username or password)/i);

      const token = await page.evaluate(() => window.localStorage.getItem('tg-signer-token'));
      expect(token).toBeNull();
    });
  });

  test('should handle mock 500 server error gracefully', async ({ page }) => {
    await page.goto('/login');

    await test.step('Mock API 500 error on login endpoint', async () => {
      await page.route('**/auth/login', (route) => {
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Internal Server Error' }),
        });
      });

      await page.locator('#login-username').fill('admin');
      await page.locator('#login-password').fill('adminpassword123');
      await page.locator('button[type="submit"]').click();

      const alert = page.getByRole('alert');
      await expect(alert).toBeVisible();
    });
  });

  test('should successfully log in with valid admin credentials', async ({ page }) => {
    await page.goto('/login');

    await test.step('Fill valid admin credentials and submit', async () => {
      await page.locator('#login-username').fill(ADMIN_USERNAME);
      await page.locator('#login-password').fill(ADMIN_PASSWORD);
      await page.locator('button[type="submit"]').click();
    });

    await test.step('Verify redirection to dashboard and token persistence', async () => {
      await expect(page).toHaveURL(/.*\/dashboard/);
      const token = await page.evaluate(() => window.localStorage.getItem('tg-signer-token'));
      expect(token).toBeTruthy();
      expect(token?.length).toBeGreaterThan(10);
    });
  });

});

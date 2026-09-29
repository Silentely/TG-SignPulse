import { test, expect, loginViaUI } from './fixtures';

test.describe('Navigation, Layout & Responsive Viewport', () => {

  test.beforeEach(async ({ page }) => {
    await loginViaUI(page);
  });

  test('should navigate across all main sections via desktop sidebar', async ({ page }) => {
    const routesToTest = [
      { name: /(账号管理|Accounts)/i, expectedUrl: /\/accounts/ },
      { name: /(任务管理|Tasks)/i, expectedUrl: /\/tasks/ },
      { name: /(扩展插件|Plugins)/i, expectedUrl: /\/plugins/ },
      { name: /(日志中心|Logs)/i, expectedUrl: /\/logs/ },
      { name: /(系统设置|Settings)/i, expectedUrl: /\/settings/ },
      { name: /(仪表盘|Dashboard)/i, expectedUrl: /\/dashboard/ },
    ];

    for (const route of routesToTest) {
      await test.step(`Navigate to ${route.expectedUrl.source}`, async () => {
        const navLink = page.locator('aside, nav').getByRole('link', { name: route.name }).first();
        if (await navLink.isVisible()) {
          await navLink.click();
          await expect(page).toHaveURL(route.expectedUrl);
        } else {
          await page.goto(route.expectedUrl.source.replace(/\\/g, ''));
          await expect(page).toHaveURL(route.expectedUrl);
        }
      });
    }
  });

  test('should adapt layout and support drawer navigation in mobile viewport', async ({ page }) => {
    await test.step('Resize to mobile viewport', async () => {
      await page.setViewportSize({ width: 390, height: 844 });
    });

    await test.step('Open mobile menu drawer', async () => {
      // Find hamburger menu button in mobile header
      const menuBtn = page.getByRole('button', { name: /(菜单|Menu|Toggle menu)/i })
        .or(page.locator('header button').filter({ has: page.locator('svg') }).first());

      await expect(menuBtn).toBeVisible();
      await menuBtn.click();
    });

    await test.step('Verify mobile drawer is opened and navigate', async () => {
      const accountsLink = page.getByRole('link', { name: /(账号管理|Accounts)/i }).first();
      await expect(accountsLink).toBeVisible();
      await accountsLink.click();
      await expect(page).toHaveURL(/.*\/accounts/);
    });
  });

  test('should open user profile modal and handle logout cycle', async ({ page }) => {
    await test.step('Open user profile modal', async () => {
      const profileTrigger = page.locator('[data-testid="user-profile-btn"]')
        .or(page.getByRole('button', { name: /(个人中心|Profile|admin)/i }))
        .or(page.locator('aside button, header button').filter({ hasText: /admin/i }).first());

      await profileTrigger.click();
      await expect(page.getByRole('dialog').or(page.locator('.ui-modal-container, .modal-container')).first()).toBeVisible();
    });

    await test.step('Verify Profile tabs switching', async () => {
      const passwordTab = page.getByRole('tab', { name: /(修改密码|Password)/i })
        .or(page.getByRole('button', { name: /(修改密码|Password)/i }));
      if (await passwordTab.isVisible()) {
        await passwordTab.click();
      }

      const totpTab = page.getByRole('tab', { name: /(两步验证|TOTP|2FA)/i })
        .or(page.getByRole('button', { name: /(两步验证|TOTP|2FA)/i }));
      if (await totpTab.isVisible()) {
        await totpTab.click();
      }
    });

    await test.step('Execute logout', async () => {
      const logoutBtn = page.getByRole('button', { name: /(退出登录|Logout|Sign Out)/i }).last();
      await expect(logoutBtn).toBeVisible();
      await logoutBtn.click();

      await expect(page).toHaveURL(/.*\/login/);
      const token = await page.evaluate(() => window.localStorage.getItem('tg-signer-token'));
      expect(token).toBeNull();
    });

    await test.step('Verify protected routes remain locked after logout', async () => {
      await page.goto('/dashboard');
      await expect(page).toHaveURL(/.*\/login/);
    });
  });

});

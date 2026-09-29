import { test, expect, loginViaUI } from './fixtures';

test.describe('Navigation, Layout & Responsive Viewport', () => {

  test.beforeEach(async ({ page }) => {
    await loginViaUI(page);
    await expect(page).toHaveURL(/.*\/dashboard/);
  });

  test('should navigate across all main sections via desktop sidebar', async ({ page }) => {
    const navItems = [
      { name: /(账号管理|Accounts)/i, urlPattern: /.*\/accounts/ },
      { name: /(任务管理|Tasks)/i, urlPattern: /.*\/tasks/ },
      { name: /(扩展插件|Plugins)/i, urlPattern: /.*\/plugins/ },
      { name: /(日志中心|Logs)/i, urlPattern: /.*\/logs/ },
      { name: /(系统设置|Settings)/i, urlPattern: /.*\/settings/ },
      { name: /(运行看板|控制台|Dashboard)/i, urlPattern: /.*\/dashboard/ },
    ];

    for (const item of navItems) {
      await test.step(`Navigate to ${item.name}`, async () => {
        const link = page.getByRole('link', { name: item.name }).first();
        if (await link.isVisible()) {
          await link.click();
          await expect(page).toHaveURL(item.urlPattern);
        }
      });
    }
  });

  test('should adapt layout and support drawer navigation in mobile viewport', async ({ page }) => {
    // Check mobile menu hamburger button exists
    const menuBtn = page.getByRole('button', { name: /(打开菜单|Open menu|Menu)/i });
    if (await menuBtn.isVisible()) {
      await menuBtn.click();
      const accountsLink = page.getByRole('link', { name: /(账号管理|Accounts)/i }).first();
      await expect(accountsLink).toBeVisible();
      await accountsLink.click();
      await expect(page).toHaveURL(/.*\/accounts/);
    }
  });

  test('should open user profile modal and handle logout cycle', async ({ page }) => {
    await test.step('Open user profile modal', async () => {
      // In mobile viewports, the aside drawer is hidden (-translate-x-full & inert) by default.
      // If mobile hamburger menu button is visible, click it first to reveal the sidebar.
      const menuBtn = page.getByRole('button', { name: /(打开菜单|Open menu|Menu)/i });
      if (await menuBtn.isVisible()) {
        await menuBtn.click();
      }

      const profileTrigger = page.locator('[data-testid="user-profile-btn"]')
        .or(page.getByRole('button', { name: /(个人中心|Profile|admin)/i }))
        .or(page.locator('aside button, header button').filter({ hasText: /admin/i }).first());

      await expect(profileTrigger).toBeVisible();
      await profileTrigger.click();
      await expect(page.getByRole('dialog').or(page.locator('.ui-modal-container, .modal-container')).first()).toBeVisible();
    });

    await test.step('Verify Profile tabs switching', async () => {
      const passwordTab = page.getByRole('tab', { name: /(\u4fee\u6539\u5bc6\u7801|Password)/i })
        .or(page.getByRole('button', { name: /(\u4fee\u6539\u5bc6\u7801|Password)/i }));
      if (await passwordTab.isVisible()) {
        await passwordTab.click();
      }

      const totpTab = page.getByRole('tab', { name: /(\u4e24\u6b65\u9a8c\u8bc1|TOTP|2FA)/i })
        .or(page.getByRole('button', { name: /(\u4e24\u6b65\u9a8c\u8bc1|TOTP|2FA)/i }));
      if (await totpTab.isVisible()) {
        await totpTab.click();
      }
    });

    await test.step('Execute logout', async () => {
      const logoutBtn = page.getByRole('button', { name: /(\u9000\u51fa\u767b\u5f55|Logout|Sign Out)/i }).last();
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

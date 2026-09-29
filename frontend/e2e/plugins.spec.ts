import { test, expect, loginViaUI } from './fixtures';

test.describe('Plugins Center & Legacy Redirects', () => {

  test.beforeEach(async ({ page }) => {
    await loginViaUI(page);
  });

  test('should redirect legacy route /settings?tab=plugins to /plugins', async ({ page }) => {
    await page.goto('/settings?tab=plugins');
    await expect(page).toHaveURL(/.*\/plugins/);
  });

  test('should render core plugins and support plugin storage inspection', async ({ page }) => {
    await page.goto('/plugins');

    await test.step('Verify plugins list and builtin plugins', async () => {
      const mathSolver = page.getByText('math_solver').or(page.getByText('数学题解答'));
      await expect(mathSolver.first()).toBeVisible();

      const dailyCheckin = page.getByText('daily_checkin_helper').or(page.getByText('每日签到助手'));
      await expect(dailyCheckin.first()).toBeVisible();
    });

    await test.step('Open and dismiss plugin storage inspection modal', async () => {
      const storageInspectBtn = page.getByRole('button', { name: /(存储|数据|Storage|Data)/i }).first();
      if (await storageInspectBtn.isVisible()) {
        await storageInspectBtn.click();
        const modal = page.getByRole('dialog').or(page.locator('.ui-modal-container'));
        if (await modal.isVisible()) {
          const closeBtn = modal.getByRole('button', { name: /(关闭|Close|取消)/i }).first();
          if (await closeBtn.isVisible()) {
            await closeBtn.click();
          } else {
            await page.keyboard.press('Escape');
          }
          await expect(modal).toBeHidden();
        }
      }
    });
  });

});

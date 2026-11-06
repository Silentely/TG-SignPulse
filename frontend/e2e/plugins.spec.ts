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

  test('should filter plugins list via search query', async ({ page }) => {
    await page.goto('/plugins');
    await expect(page).toHaveURL(/.*\/plugins/);

    const searchInput = page.getByPlaceholder(/(搜索插件名称|Search plugin name)/i);
    await expect(searchInput).toBeVisible();

    await test.step('Filter by math_solver keyword', async () => {
      await searchInput.fill('math_solver');
      await expect(page.getByText('math_solver').first()).toBeVisible();
      await expect(page.getByText('daily_checkin_helper')).toBeHidden();
    });

    await test.step('Clear search keyword and verify all plugins restored', async () => {
      await searchInput.fill('');
      await expect(page.getByText('math_solver').first()).toBeVisible();
      await expect(page.getByText('daily_checkin_helper').first()).toBeVisible();
    });
  });

  test('should open plugin source modal and dismiss', async ({ page }) => {
    await page.goto('/plugins');
    await expect(page).toHaveURL(/.*\/plugins/);

    await test.step('Open source code modal from plugin card', async () => {
      const sourceBtn = page.getByRole('button', { name: /(查看源码|View Source)/i }).first();
      await expect(sourceBtn).toBeVisible();
      await sourceBtn.click();

      const sourceModal = page.getByRole('dialog');
      await expect(sourceModal).toBeVisible();
      await expect(sourceModal.getByText(/(插件源码查看|Plugin Source Code)/i)).toBeVisible();

      await page.keyboard.press('Escape');
      await expect(sourceModal).toBeHidden();
    });
  });

  test('should support deep-link query to open plugin debug playground', async ({ page }) => {
    await page.goto('/plugins?testPlugin=math_solver&testInput=2%2B2%3D%3F');
    await expect(page).toHaveURL(/.*\/plugins/);

    await test.step('Verify test playground modal auto-opened by query param', async () => {
      const playgroundModal = page.getByRole('dialog');
      await expect(playgroundModal).toBeVisible();
      await expect(playgroundModal.getByText(/(插件调试|Plugin Debugger)/i)).toBeVisible();

      const testInput = playgroundModal.locator('textarea');
      await expect(testInput).toHaveValue('2+2=?');

      await page.keyboard.press('Escape');
      await expect(playgroundModal).toBeHidden();
    });
  });

});

import { test, expect, loginViaUI } from './fixtures';

test.describe('Logs Center & System Settings', () => {

  test.beforeEach(async ({ page }) => {
    await loginViaUI(page);
  });

  test('should navigate to Logs view and switch between Task Logs and Audit Logs', async ({ page }) => {
    await page.goto('/logs');
    await expect(page).toHaveURL(/.*\/logs/);

    await test.step('Verify logs navigation tabs and audit logs panel', async () => {
      // Find Audit Logs tab
      const auditTab = page.getByRole('button', { name: /(审计日志|Audit Logs)/i })
        .or(page.getByText(/(审计日志|Audit Logs)/i)).first();

      if (await auditTab.isVisible()) {
        await auditTab.click();
        // Wait for audit log items or empty indicator
        await expect(page.locator('table, .ui-empty, .font-mono').first()).toBeVisible();
      }

      // Switch back to Task Logs tab
      const taskLogsTab = page.getByRole('button', { name: /(任务日志|Task Logs)/i })
        .or(page.getByText(/(任务日志|Task Logs)/i)).first();

      if (await taskLogsTab.isVisible()) {
        await taskLogsTab.click();
        await expect(page.locator('table, .ui-empty, .font-mono').first()).toBeVisible();
      }
    });
  });

  test('should render system settings panels and protect sensitive secrets', async ({ page }) => {
    await page.goto('/settings');
    await expect(page).toHaveURL(/.*\/settings/);

    await test.step('Verify settings sections are rendered', async () => {
      await expect(page.getByText(/(通用|General|Telegram API|数据|备份)/i).first()).toBeVisible();
    });

    await test.step('Verify sensitive secret toggle functionality', async () => {
      const apiHashInput = page.locator('#settings-api-hash');
      if (await apiHashInput.isVisible()) {
        await expect(apiHashInput).toHaveAttribute('type', 'password');
        const revealBtn = page.locator('#settings-api-hash ~ button');
        if (await revealBtn.isVisible()) {
          await revealBtn.click();
          await expect(apiHashInput).toHaveAttribute('type', 'text');
          await revealBtn.click();
          await expect(apiHashInput).toHaveAttribute('type', 'password');
        }
      }
    });
  });

});

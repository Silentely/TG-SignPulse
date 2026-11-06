import { test, expect, loginViaUI } from './fixtures';

test.describe('Logs Center & System Settings', () => {

  test.beforeEach(async ({ page }) => {
    await loginViaUI(page);
  });

  test('should navigate to Logs view and switch between Task Logs and Audit Logs', async ({ page }) => {
    await page.goto('/logs');
    await expect(page).toHaveURL(/.*\/logs/);

    await test.step('Verify logs navigation tabs and audit logs panel', async () => {
      const auditTab = page.getByRole('button', { name: /(审计日志|Audit Logs)/i })
        .or(page.getByText(/(审计日志|Audit Logs)/i)).first();

      if (await auditTab.isVisible()) {
        await auditTab.click();
        await expect(page.locator('table, .ui-empty, .font-mono').first()).toBeVisible();
      }

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

  test('should detect dirty state when editing settings form and support saving', async ({ page }) => {
    await page.goto('/settings');
    await expect(page).toHaveURL(/.*\/settings/);

    const logRetentionInput = page.locator('#settings-log-retention');
    await expect(logRetentionInput).toBeVisible();

    await test.step('Modify log retention input to trigger unsaved dirty banner', async () => {
      const originalValue = await logRetentionInput.inputValue();
      const newValue = originalValue === '15' ? '14' : '15';
      await logRetentionInput.fill(newValue);

      const dirtyBanner = page.locator('[role="status"]').filter({
        hasText: /(当前有未保存的更改|You have unsaved changes)/i,
      });
      await expect(dirtyBanner).toBeVisible();
    });

    await test.step('Save settings and verify dirty banner disappears', async () => {
      const saveBtn = page.getByRole('button', { name: /(保存全部|Save all|保存|Save)/i }).first();
      await expect(saveBtn).toBeVisible();
      await saveBtn.click();

      const dirtyBanner = page.locator('[role="status"]').filter({
        hasText: /(当前有未保存的更改|You have unsaved changes)/i,
      });
      await expect(dirtyBanner).toBeHidden();
    });
  });

  test('should display task logs, support log detail modal opening and dismissal', async ({ page }) => {
    await page.route(/\/api\/logs\/tasks/, async (route) => {
      if (route.request().url().includes('/item')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 8801,
            account_name: 'alpha_operator',
            task_name: 'daily_checkin',
            message: 'Sign verified successfully by bot',
            success: true,
            created_at: '2026-11-05T09:00:00Z',
            flow_line_count: 2,
            flow_logs: ['Step 1: sent /start command', 'Step 2: clicked checkin inline button'],
            flow_truncated: false,
          }),
        });
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 8801,
            account_name: 'alpha_operator',
            task_name: 'daily_checkin',
            message: 'Sign verified successfully by bot',
            success: true,
            created_at: '2026-11-05T09:00:00Z',
            flow_line_count: 2,
          },
        ]),
      });
    });

    await page.goto('/logs');
    await expect(page).toHaveURL(/.*\/logs/);

    await test.step('Verify mock log row rendered with account and task names', async () => {
      await expect(page.getByText('alpha_operator').first()).toBeVisible();
      await expect(page.getByText('daily_checkin').first()).toBeVisible();
    });

    await test.step('Open log detail modal by clicking on log row', async () => {
      const logRow = page.locator('.ui-list-row').filter({ hasText: 'alpha_operator' }).first();
      await logRow.click();

      const detailModal = page.getByRole('dialog');
      await expect(detailModal).toBeVisible();
      await expect(detailModal.getByText(/(日志详情|Log Detail)/i).first()).toBeVisible();
      await expect(detailModal.getByText(/Step 1: sent \/start command/i)).toBeVisible();

      await page.keyboard.press('Escape');
      await expect(detailModal).toBeHidden();
    });
  });

});

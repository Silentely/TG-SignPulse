import type { Page } from '@playwright/test';
import { test, expect, loginViaUI } from './fixtures';

const HEALTH_ACCOUNTS = [
  {
    name: 'acc_ok',
    session_file: 'acc_ok.session',
    exists: true,
    size: 100,
    status: 'connected',
    remark: '正常账号',
    needs_relogin: false,
  },
  {
    name: 'acc_expired',
    session_file: 'acc_expired.session',
    exists: true,
    size: 100,
    status: 'invalid',
    status_message: 'Session 已失效',
    status_code: 'API_CREDENTIALS_MISMATCH',
    remark: '主力账号',
    needs_relogin: true,
    use_custom_api: true,
    api_id: 11122233,
    has_api_hash: true,
    api_hash_masked: 'save****alue',
  },
  {
    name: 'acc_blocked',
    session_file: 'acc_blocked.session',
    exists: true,
    size: 100,
    status: 'blocked',
    status_message: 'PROXY_BLOCKED: 代理不可达',
    status_code: 'PROXY_BLOCKED',
    remark: '代理账号',
    needs_relogin: false,
  },
];

async function mockAccounts(page: Page, accounts: unknown[]) {
  await page.route('**/api/accounts', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ accounts, total: accounts.length }),
    });
  });
}

test.describe('Dashboard Account Health', () => {
  test('should classify account health, consume relogin deep link once and echo saved credentials', async ({ page }) => {
    await mockAccounts(page, HEALTH_ACCOUNTS);
    await loginViaUI(page);

    const healthCard = page.locator('.ui-card').filter({ hasText: '账号健康与预警' });

    await test.step('Verify health counts and account groups', async () => {
      await expect(healthCard).toBeVisible();
      await expect(healthCard.getByText('正常: 1')).toBeVisible();
      await expect(healthCard.getByText('需重登: 1')).toBeVisible();
      await expect(healthCard.getByText('待重试: 1')).toBeVisible();
      await expect(healthCard.getByText('所有账号状态健康')).toBeHidden();

      const reloginRow = healthCard.getByTestId('account-health-relogin');
      await expect(reloginRow).toContainText('acc_expired');
      await expect(reloginRow).toContainText('主力账号');

      const retryRow = healthCard.getByTestId('account-health-retry');
      await expect(retryRow).toContainText('acc_blocked');
      await expect(retryRow).toContainText('PROXY_BLOCKED: 代理不可达');
    });

    await test.step('Open account edit modal from the relogin action', async () => {
      await healthCard.getByTestId('account-health-relogin').getByRole('button', { name: '去重新登录' }).click();
      await expect(page).toHaveURL(/\/accounts/);
      await expect(page).not.toHaveURL(/account=/);

      const editDialog = page.getByRole('dialog', { name: '编辑账号' });
      await expect(editDialog).toBeVisible();
      await editDialog.getByRole('button', { name: /高级设置/ }).click();
      await expect(editDialog.locator('input[id^="account-api-id-"]')).toHaveValue('11122233');
      await expect(editDialog.getByText('当前已保存 Hash：save****alue')).toBeVisible();
    });

    await test.step('Carry saved credentials into the relogin modal and validate ID changes', async () => {
      const editDialog = page.getByRole('dialog', { name: '编辑账号' });
      await editDialog.getByRole('button', { name: /重新登录/ }).click();

      const reloginDialog = page.getByRole('dialog', { name: '验证码登录' });
      await expect(reloginDialog).toBeVisible();
      await reloginDialog.getByRole('button', { name: /高级设置/ }).click();

      const apiIdInput = reloginDialog.locator('input[id^="account-api-id-"]');
      await expect(apiIdInput).toHaveValue('11122233');

      await apiIdInput.fill('999999');
      await expect(reloginDialog.getByRole('alert')).toContainText(
        '改动 API ID 时必须同时填写 API Hash',
      );

      await reloginDialog.getByRole('button', { name: /取消/ }).last().click();
      await expect(reloginDialog).toBeHidden();
    });

    await test.step('Reloading the accounts page does not reopen the consumed deep link', async () => {
      await page.goto('/accounts');
      await page.reload();
      await expect(page.getByRole('dialog')).toBeHidden();
      await expect(page).not.toHaveURL(/account=/);
    });
  });

  test('should show the empty state instead of all accounts healthy when no accounts exist', async ({ page }) => {
    await mockAccounts(page, []);
    await loginViaUI(page);

    const healthCard = page.locator('.ui-card').filter({ hasText: '账号健康与预警' });
    await expect(healthCard).toBeVisible();
    await expect(healthCard.getByText('正常: 0')).toBeVisible();
    await expect(healthCard.getByText('还没有 Telegram 账号')).toBeVisible();
    await expect(healthCard.getByText('所有账号状态健康')).toBeHidden();
  });
});

import { test, expect, loginViaUI } from './fixtures';

const MOCK_ACCOUNTS_LIST = [
  {
    name: 'alpha_operator',
    id: 'acc_alpha_id',
    phone: '+1234567890',
    status: 'active',
    remark: 'Production Bot 1',
  },
  {
    name: 'beta_tester',
    id: 'acc_beta_id',
    phone: '+1987654321',
    status: 'active',
    remark: 'QA Staging Bot',
  },
];

test.describe('Accounts Management & Modal Workflows', () => {

  test.beforeEach(async ({ page }) => {
    await loginViaUI(page);
  });

  test('should render accounts page and support search filtering', async ({ page }) => {
    await page.goto('/accounts');
    await expect(page).toHaveURL(/.*\/accounts/);

    await test.step('Verify accounts page container is rendered', async () => {
      await expect(page.locator('.ui-empty, .ui-card').first()).toBeVisible();
    });

    await test.step('Search input filtering and clear action', async () => {
      const searchInput = page.getByRole('searchbox')
        .or(page.locator('input[type="search"]'));

      if (await searchInput.isVisible()) {
        await searchInput.fill('test_search_filter');
        await expect(searchInput).toHaveValue('test_search_filter');

        const clearBtn = page.locator('button').filter({ has: page.locator('svg.lucide-x, svg.lucide-circle-x') }).first();
        if (await clearBtn.isVisible()) {
          await clearBtn.click();
          await expect(searchInput).toHaveValue('');
        } else {
          await searchInput.fill('');
        }
      }
    });
  });

  test('should open Add Account modal, switch tabs and validate inputs', async ({ page }) => {
    await page.goto('/accounts');
    await expect(page).toHaveURL(/.*\/accounts/);

    await test.step('Trigger Add Account modal', async () => {
      const emptyAddBtn = page.locator('.ui-empty button').first();
      if (await emptyAddBtn.isVisible()) {
        await emptyAddBtn.click();
      } else {
        const fabBtn = page.locator('button.ui-fab');
        await fabBtn.click();
        const codeOptionBtn = page.getByRole('button', { name: /(验证码登录|Code Login)/i }).last();
        await codeOptionBtn.click();
      }
    });

    const modal = page.getByRole('dialog').or(page.locator('.ui-modal-container'));
    await expect(modal).toBeVisible();

    await test.step('Switch login methods via segmented buttons', async () => {
      const qrBtn = modal.getByRole('button', { name: /(扫码登录|QR Login)/i });
      if (await qrBtn.isVisible()) {
        await qrBtn.click();
        await expect(qrBtn).toHaveAttribute('aria-pressed', 'true');
      }

      const importBtn = modal.getByRole('button', { name: /(导入 Session|Import Session)/i });
      if (await importBtn.isVisible()) {
        await importBtn.click();
        await expect(importBtn).toHaveAttribute('aria-pressed', 'true');
      }

      const codeBtn = modal.getByRole('button', { name: /(验证码登录|Code Login)/i });
      if (await codeBtn.isVisible()) {
        await codeBtn.click();
        await expect(codeBtn).toHaveAttribute('aria-pressed', 'true');
      }
    });

    await test.step('Validate required fields when submitting empty form', async () => {
      const nameInput = page.locator('#add-account-name');
      const phoneInput = page.locator('#add-account-phone');

      await nameInput.fill('');
      if (await phoneInput.isVisible()) {
        await phoneInput.fill('');
      }

      const sendCodeBtn = modal.getByRole('button', { name: /(发送验证码|Send Code)/i });
      if (await sendCodeBtn.isVisible()) {
        await sendCodeBtn.click();
        const errorAlert = modal.getByRole('alert');
        await expect(errorAlert).toBeVisible();
      }
    });

    await test.step('Close modal gracefully via close button or Escape', async () => {
      const cancelBtn = modal.getByRole('button', { name: /(取消|Cancel)/i });
      if (await cancelBtn.isVisible()) {
        await cancelBtn.click();
      } else {
        await page.keyboard.press('Escape');
      }

      await expect(modal).toBeHidden();
    });
  });

  test('should render account cards, support search filter and open device management modal', async ({ page }) => {
    await page.route('**/api/accounts', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          accounts: MOCK_ACCOUNTS_LIST,
          total: MOCK_ACCOUNTS_LIST.length,
        }),
      });
    });

    await page.route('**/api/accounts/*/devices', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total: 1,
          devices: [
            {
              hash: 'dev_hash_123',
              device_model: 'MacBook Pro E2E',
              platform: 'macOS',
              system_version: '15.0',
              api_id: 12345,
              app_name: 'SignPulse Runner',
              app_version: '2.7.0',
              date_created: '2026-11-01T08:00:00Z',
              date_active: '2026-11-05T09:00:00Z',
              ip: '127.0.0.1',
              country: 'Local',
              current: true,
            },
          ],
        }),
      });
    });

    await page.goto('/accounts');
    await expect(page.getByText('alpha_operator')).toBeVisible();
    await expect(page.getByText('beta_tester')).toBeVisible();

    const searchInput = page.getByRole('searchbox').or(page.locator('input[type="search"]'));

    await test.step('Search filter reduces visible accounts to matching item', async () => {
      await searchInput.fill('alpha_operator');
      await expect(page.getByText('alpha_operator')).toBeVisible();
      await expect(page.getByText('beta_tester')).toBeHidden();

      await searchInput.fill('');
      await expect(page.getByText('beta_tester')).toBeVisible();
    });

    const alphaCard = page.locator('.ui-card').filter({ hasText: 'alpha_operator' });

    await test.step('Open device management modal and inspect authorized devices', async () => {
      const devicesBtn = alphaCard.getByRole('button', { name: /(设备|Devices)/i });
      await devicesBtn.scrollIntoViewIfNeeded();
      await devicesBtn.click();

      const modal = page.getByRole('dialog').or(page.locator('.ui-modal-container'));
      await expect(modal).toBeVisible();
      await expect(modal.getByText('MacBook Pro E2E')).toBeVisible();

      await page.keyboard.press('Escape');
      await expect(modal).toBeHidden();
    });
  });

  test('should open official telegram messages modal and display messages list', async ({ page }) => {
    await page.route('**/api/accounts', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          accounts: MOCK_ACCOUNTS_LIST,
          total: MOCK_ACCOUNTS_LIST.length,
        }),
      });
    });

    await page.route('**/api/accounts/*/official-messages*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total: 1,
          messages: [
            {
              id: 777001,
              date: '2026-11-05T09:30:00Z',
              text: 'Login code: 998877. Do not share this code.',
            },
          ],
        }),
      });
    });

    await page.goto('/accounts');
    await expect(page.getByText('alpha_operator')).toBeVisible();

    const alphaCard = page.locator('.ui-card').filter({ hasText: 'alpha_operator' });
    const officialBtn = alphaCard.getByRole('button', { name: /(官方|Official)/i });
    await officialBtn.scrollIntoViewIfNeeded();
    await officialBtn.click();

    const modal = page.getByRole('dialog').or(page.locator('.ui-modal-container'));
    await expect(modal).toBeVisible();
    await expect(modal.getByText('Login code: 998877')).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(modal).toBeHidden();
  });

  test('should open account lifecycle delete impact modal and handle cancellation', async ({ page }) => {
    await page.route('**/api/accounts', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          accounts: MOCK_ACCOUNTS_LIST,
          total: MOCK_ACCOUNTS_LIST.length,
        }),
      });
    });

    await page.route('**/api/accounts/*/lifecycle/preview', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          operation: 'delete',
          old_name: 'alpha_operator',
          affected_tasks: [{ name: 'daily_bot_task' }],
          affected_jobs: ['job_daily_checkin'],
          affected_monitors: [],
          history_paths: ['/tmp/history/alpha.json'],
          history_policy: 'retain',
          plugin_namespaces: ['math_solver'],
          reversible_steps: [],
          warnings: ['This account is referenced by 1 active task.'],
          revision: 'rev_123',
        }),
      });
    });

    await page.goto('/accounts');
    await expect(page.getByText('alpha_operator')).toBeVisible();

    const alphaCard = page.locator('.ui-card').filter({ hasText: 'alpha_operator' });
    const deleteBtn = alphaCard.getByRole('button', { name: /(删除|Delete)/i });
    await deleteBtn.scrollIntoViewIfNeeded();
    await deleteBtn.click();

    const impactModal = page.getByRole('dialog').or(page.locator('.ui-modal-container'));
    await expect(impactModal).toBeVisible();
    await expect(impactModal.getByText(/(Account change impact|账号变更影响)/i)).toBeVisible();
    await expect(impactModal.getByText('daily_bot_task')).toBeVisible();

    const cancelBtn = impactModal.getByRole('button', { name: /(Cancel|取消)/i });
    await cancelBtn.click();

    await expect(impactModal).toBeHidden();
    await expect(page.getByText('alpha_operator')).toBeVisible();
  });

});

import { test, expect, loginViaUI } from './fixtures';

test.describe('Accounts Management & Modal Workflows', () => {

  test.beforeEach(async ({ page }) => {
    await loginViaUI(page);
    await page.goto('/accounts');
    await expect(page).toHaveURL(/.*\/accounts/);
  });

  test('should render accounts page and support search filtering', async ({ page }) => {
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

});

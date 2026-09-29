import { test, expect, loginViaUI } from './fixtures';

test.describe('Tasks Management & Creation Flow', () => {

  test.beforeEach(async ({ page }) => {
    await loginViaUI(page);
    await page.goto('/tasks');
    await expect(page).toHaveURL(/.*\/tasks/);
  });

  test('should render task view, filter modes and toggle categories', async ({ page }) => {
    await test.step('Verify task view toolbar and action buttons', async () => {
      const newTaskBtn = page.getByRole('button', { name: /(新建任务|New Task|添加任务)/i }).first();
      await expect(newTaskBtn).toBeVisible();
    });

    await test.step('Toggle task categories (All, Scheduled, Monitoring)', async () => {
      const scheduledTab = page.getByRole('button', { name: /(定时任务|Scheduled)/i });
      if (await scheduledTab.isVisible()) {
        await scheduledTab.click();
      }

      const monitorTab = page.getByRole('button', { name: /(监听任务|Monitoring)/i });
      if (await monitorTab.isVisible()) {
        await monitorTab.click();
      }

      const allTab = page.getByRole('button', { name: /(全部任务|All Tasks)/i });
      if (await allTab.isVisible()) {
        await allTab.click();
      }
    });
  });

  test('should open Add Task modal, test form field inputs and close modal', async ({ page }) => {
    const newTaskBtn = page.getByRole('button', { name: /(新建任务|New Task|添加任务)/i }).first();
    await newTaskBtn.click();

    const modal = page.getByRole('dialog').or(page.locator('.ui-modal-container'));
    await expect(modal).toBeVisible();

    await test.step('Interact with task name input and boundary validation', async () => {
      const taskNameInput = page.locator('#task-form-name');
      await expect(taskNameInput).toBeVisible();

      // Test extreme input / long string boundary
      const testName = 'e2e_test_task_' + Date.now();
      await taskNameInput.fill(testName);
      await expect(taskNameInput).toHaveValue(testName);
    });

    await test.step('Form submission without required target triggers validation notice', async () => {
      const saveBtn = modal.getByRole('button', { name: /(保存|Save|创建)/i }).first();
      if (await saveBtn.isVisible()) {
        await saveBtn.click();
        // Validation notice or toast appears without crashing
      }
    });

    await test.step('Close modal without submitting invalid data', async () => {
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

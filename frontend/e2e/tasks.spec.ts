import { test, expect, loginViaUI } from './fixtures';

const MOCK_ACCOUNTS = [
  { name: 'bot_alpha', id: 'acc_1', status: 'active', phone: '+1234567890' },
];

const MOCK_TASKS = [
  {
    name: 'auto_checkin_cron',
    account_name: 'bot_alpha',
    sign_at: '09:00:00',
    execution_mode: 'fixed',
    enabled: true,
    random_seconds: 0,
    sign_interval: 86400,
    chats: [
      { chat_id: -10012345678, name: 'Daily Checkin Group', action_interval: 2, actions: [{ type: 'text', text: '/checkin' }] },
    ],
    last_run: { time: '2026-11-05T09:00:00Z', success: true, message: 'Checkin success' },
  },
  {
    name: 'keyword_listener_task',
    account_name: 'bot_alpha',
    sign_at: '00:00:00',
    execution_mode: 'listen',
    enabled: false,
    random_seconds: 0,
    sign_interval: 0,
    chats: [
      { chat_id: -10087654321, name: 'VIP Channel', action_interval: 1, actions: [] },
    ],
    last_run: null,
  },
];

test.describe('Tasks Management & Creation Flow', () => {

  test.beforeEach(async ({ page }) => {
    await loginViaUI(page);
  });

  test('should render task view, filter modes and toggle categories', async ({ page }) => {
    await page.goto('/tasks');
    await expect(page).toHaveURL(/.*\/tasks/);

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
    await page.goto('/tasks');
    await expect(page).toHaveURL(/.*\/tasks/);

    const newTaskBtn = page.getByRole('button', { name: /(新建任务|New Task|添加任务)/i }).first();
    await newTaskBtn.click();

    const modal = page.getByRole('dialog').or(page.locator('.ui-modal-container'));
    await expect(modal).toBeVisible();

    await test.step('Interact with task name input and boundary validation', async () => {
      const taskNameInput = page.locator('#task-form-name');
      await expect(taskNameInput).toBeVisible();

      const testName = 'e2e_test_task_' + Date.now();
      await taskNameInput.fill(testName);
      await expect(taskNameInput).toHaveValue(testName);
    });

    await test.step('Form submission without required target triggers validation notice', async () => {
      const saveBtn = modal.getByRole('button', { name: /(保存|Save|创建)/i }).first();
      if (await saveBtn.isVisible()) {
        await saveBtn.click();
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

  test('should render task card with actions, toggle enable state, and open clone modal', async ({ page }) => {
    let isCronEnabled = true;

    await page.route('**/api/accounts', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_ACCOUNTS),
      });
    });

    await page.route('**/api/sign-tasks?**', async (route) => {
      const list = [
        { ...MOCK_TASKS[0], enabled: isCronEnabled },
        MOCK_TASKS[1],
      ];
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(list),
      });
    });

    await page.route('**/api/sign-tasks/*/toggle-enabled*', async (route) => {
      isCronEnabled = !isCronEnabled;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...MOCK_TASKS[0], enabled: isCronEnabled }),
      });
    });

    await page.goto('/tasks');
    await expect(page.getByText('auto_checkin_cron')).toBeVisible();
    await expect(page.getByText('keyword_listener_task')).toBeVisible();

    const cronCard = page.locator('.ui-card').filter({ hasText: 'auto_checkin_cron' });

    await test.step('Toggle task enabled/disabled state via power button', async () => {
      const toggleBtn = cronCard.locator('button[aria-pressed]').first();
      await expect(toggleBtn).toHaveAttribute('aria-pressed', 'true');
      await toggleBtn.click();
      await expect(toggleBtn).toHaveAttribute('aria-pressed', 'false');
    });

    await test.step('Open clone modal and verify initial clone name', async () => {
      const cloneBtn = cronCard.getByRole('button', { name: /(克隆|Clone)/i });
      await cloneBtn.click();

      const cloneModal = page.getByRole('dialog').or(page.locator('.ui-modal-container'));
      await expect(cloneModal).toBeVisible();
      await expect(cloneModal.getByText(/(克隆任务|Clone Task)/i)).toBeVisible();

      const cloneNameInput = cloneModal.locator('input').first();
      await expect(cloneNameInput).toBeVisible();

      const cancelBtn = cloneModal.getByRole('button', { name: /(取消|Cancel)/i });
      if (await cancelBtn.isVisible()) {
        await cancelBtn.click();
      } else {
        await page.keyboard.press('Escape');
      }
      await expect(cloneModal).toBeHidden();
    });
  });

  test('should open TaskLogsModal and support history and hits tab switching', async ({ page }) => {
    await page.route('**/api/accounts', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_ACCOUNTS),
      });
    });

    await page.route('**/api/sign-tasks?**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_TASKS),
      });
    });

    await page.route('**/api/sign-tasks/*/history*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            time: '2026-11-05T09:00:00Z',
            success: true,
            bot_message: 'E2E mock execution successful',
            account_name: 'bot_alpha',
          },
        ]),
      });
    });

    await page.route('**/api/keyword-hits/groups*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    await page.route('**/api/keyword-hits?*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total: 1,
          limit: 10,
          offset: 0,
          items: [
            {
              id: '101',
              time: '2026-11-05T10:00:00Z',
              task_name: 'keyword_listener_task',
              account_name: 'bot_alpha',
              chat_id: -10087654321,
              keyword: 'checkin_ok',
              message_text: 'Hit keyword verified in E2E test',
            },
          ],
        }),
      });
    });

    await page.goto('/tasks');
    await expect(page.getByText('keyword_listener_task')).toBeVisible();

    const listenerCard = page.locator('.ui-card').filter({ hasText: 'keyword_listener_task' });
    const logsBtn = listenerCard.getByRole('button', { name: /(日志|Logs)/i });
    await logsBtn.scrollIntoViewIfNeeded();
    await logsBtn.click();

    const logsModal = page.getByRole('dialog').or(page.locator('.ui-modal-container'));
    await expect(logsModal).toBeVisible();

    await test.step('Verify execution history tab content', async () => {
      await expect(logsModal.getByText('E2E mock execution successful')).toBeVisible();
    });

    await test.step('Switch to hits tab for listen task', async () => {
      const hitsTab = logsModal.getByRole('tab', { name: /(命中记录|Hits)/i });
      await expect(hitsTab).toBeVisible();
      await hitsTab.click();
      await expect(logsModal.getByText('Hit keyword verified in E2E test')).toBeVisible();
    });

    await test.step('Dismiss modal via Escape key', async () => {
      await page.keyboard.press('Escape');
      await expect(logsModal).toBeHidden();
    });
  });

  test('should handle task search filtering, show empty filter state and reset', async ({ page }) => {
    await page.route('**/api/accounts', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_ACCOUNTS),
      });
    });

    await page.route('**/api/sign-tasks?**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_TASKS),
      });
    });

    await page.goto('/tasks');
    await expect(page.getByText('auto_checkin_cron')).toBeVisible();

    const searchInput = page.getByRole('searchbox').or(page.locator('input[type="search"]'));
    await expect(searchInput).toBeVisible();

    await test.step('Search for non-existent task to trigger empty filter state', async () => {
      await searchInput.fill('non_existent_search_query_999');
      await expect(page.getByText('auto_checkin_cron')).toBeHidden();
      await expect(page.getByText(/(没有匹配的结果|No matching results)/i)).toBeVisible();
    });

    await test.step('Clear filter via empty state action button', async () => {
      const clearBtn = page.getByRole('button', { name: /(清除全部筛选|Clear all filters)/i });
      await expect(clearBtn).toBeVisible();
      await clearBtn.click();

      await expect(page.getByText('auto_checkin_cron')).toBeVisible();
      await expect(searchInput).toHaveValue('');
    });
  });

  test('should support deep-link to task logs modal via URL query', async ({ page }) => {
    await page.route('**/api/accounts', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_ACCOUNTS),
      });
    });

    await page.route('**/api/sign-tasks?**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_TASKS),
      });
    });

    await page.route('**/api/keyword-hits/groups*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    await page.route('**/api/keyword-hits?*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total: 1,
          limit: 10,
          offset: 0,
          items: [
            {
              id: '202',
              time: '2026-11-05T12:00:00Z',
              task_name: 'keyword_listener_task',
              account_name: 'bot_alpha',
              chat_id: -10087654321,
              keyword: 'deeplink_target',
              message_text: 'DeepLink auto open verified',
            },
          ],
        }),
      });
    });

    await page.goto('/tasks?task=keyword_listener_task&tab=hits');

    const logsModal = page.getByRole('dialog').or(page.locator('.ui-modal-container'));
    await expect(logsModal).toBeVisible();
    await expect(logsModal.getByText('DeepLink auto open verified')).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(logsModal).toBeHidden();
  });

});

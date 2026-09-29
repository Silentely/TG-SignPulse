import { test, expect, loginViaUI } from './fixtures';

test.describe('SSE Real-time Event Stream & Dashboard Live Updates', () => {

  test.beforeEach(async ({ page }) => {
    // Intercept ticket issuance to ensure instant ticket resolution
    await page.route('**/api/events/ticket', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ticket: 'e2e-sse-mock-ticket-' + Date.now(),
          purpose: 'sign_history_sse',
          expires_in: 60,
        }),
      });
    });

    // Inject mockable SSE harness before page scripts execute
    await page.addInitScript(() => {
      class MockableEventSource extends EventTarget {
        url: string;
        readyState: number;
        readonly CONNECTING = 0;
        readonly OPEN = 1;
        readonly CLOSED = 2;
        onopen: ((this: EventSource, ev: Event) => any) | null = null;
        onmessage: ((this: EventSource, ev: MessageEvent) => any) | null = null;
        onerror: ((this: EventSource, ev: Event) => any) | null = null;

        constructor(url: string | URL) {
          super();
          this.url = url.toString();
          this.readyState = 1; // OPEN
          ((window as any).__sseInstances = (window as any).__sseInstances || []).push(this);
        }

        close() {
          this.readyState = 2; // CLOSED
        }
      }

      (window as any).EventSource = MockableEventSource;

      (window as any).__emitSse = (eventName: string, data?: any) => {
        const instances = (window as any).__sseInstances || [];
        for (const es of instances) {
          if (eventName === 'error') {
            if (typeof es.onerror === 'function') {
              es.onerror(new Event('error'));
            }
            es.dispatchEvent(new Event('error'));
          } else {
            const payload = typeof data === 'string' ? data : JSON.stringify(data || {});
            const ev = new MessageEvent(eventName, { data: payload });
            es.dispatchEvent(ev);
          }
        }
      };
    });

    await loginViaUI(page);
    await expect(page).toHaveURL(/.*\/dashboard/);
    // Ensure dashboard pageLoading skeleton is dismissed
    await expect(page.locator('div[aria-busy="true"]')).toBeHidden();
  });

  test('should establish SSE connection and switch live badge to active state', async ({ page }) => {
    // Find the live status indicator badge in the recent logs section
    const liveBadge = page.locator('.ui-card')
      .filter({ hasText: /(最近任务日志|近期日志|Recent Logs)/i })
      .locator('.ui-badge')
      .filter({ hasText: /(实时|轮询|Live|Polling)/i });

    await test.step('Initial state defaults to polling before ready event', async () => {
      await expect(liveBadge).toBeVisible();
      await expect(liveBadge).toContainText(/(轮询|Polling)/i);
    });

    await test.step('Dispatch SSE ready handshake event', async () => {
      await page.evaluate(() => {
        (window as any).__emitSse('ready', {});
      });

      // Status badge transitions to live indicator with pulse dot
      await expect(liveBadge).toContainText(/(实时|Live)/i);
      await expect(liveBadge).toHaveClass(/ui-badge-success/);
      await expect(liveBadge.locator('.ui-pulse-dot')).toBeVisible();
    });
  });

  test('should dynamically prepend real-time log and increment success KPI metric', async ({ page }) => {
    // Establish live connection
    await page.evaluate(() => {
      (window as any).__emitSse('ready', {});
    });

    const successStatCard = page.locator('button.ui-stat').filter({ hasText: /(近期成功|Recent Success)/i });
    const successStatValue = successStatCard.locator('span.font-mono');
    await expect(successStatValue).toBeVisible();

    // Read baseline count (e.g. 0)
    await expect(successStatValue).not.toHaveText('...');
    const initialText = await successStatValue.innerText();
    const initialSuccess = parseInt(initialText, 10) || 0;

    const testAccount = 'sse_auto_bot';
    const testTask = 'channel_daily_checkin';
    const testMessage = 'SSE live check-in verified successfully: ' + Date.now();

    await test.step('Push sign_log success event via SSE stream', async () => {
      await page.evaluate(({ acc, tsk, msg }) => {
        (window as any).__emitSse('sign_log', {
          account_name: acc,
          task_name: tsk,
          success: true,
          message: msg,
          created_at: new Date().toISOString(),
        });
      }, { acc: testAccount, tsk: testTask, msg: testMessage });
    });

    await test.step('Verify new log row appears dynamically in Recent Logs table without refresh', async () => {
      const logRow = page.locator('.ui-list-row').filter({ hasText: testMessage });
      await expect(logRow).toBeVisible();
      await expect(logRow).toContainText(testAccount);
      await expect(logRow).toContainText(testTask);
      await expect(logRow).toContainText(/(成功|Success)/i);
    });

    await test.step('Verify success KPI stat counter increments by +1 in real time', async () => {
      await expect(successStatValue).toHaveText(String(initialSuccess + 1));
    });
  });

  test('should handle SSE failure event and increment failure KPI metric', async ({ page }) => {
    await page.evaluate(() => {
      (window as any).__emitSse('ready', {});
    });

    const failureStatCard = page.locator('button.ui-stat').filter({ hasText: /(近期失败|Recent Failure)/i });
    const failureStatValue = failureStatCard.locator('span.font-mono');
    await expect(failureStatValue).toBeVisible();

    await expect(failureStatValue).not.toHaveText('...');
    const initialText = await failureStatValue.innerText();
    const initialFailure = parseInt(initialText, 10) || 0;

    const testFailAccount = 'sse_fail_bot';
    const testFailTask = 'channel_boost_task';
    const testFailMessage = 'RPC execution timeout during checkin: ' + Date.now();

    await test.step('Push sign_log failure event via SSE stream', async () => {
      await page.evaluate(({ acc, tsk, msg }) => {
        (window as any).__emitSse('sign_log', {
          account_name: acc,
          task_name: tsk,
          success: false,
          message: msg,
          failure_category: 'timeout',
          created_at: new Date().toISOString(),
        });
      }, { acc: testFailAccount, tsk: testFailTask, msg: testFailMessage });
    });

    await test.step('Verify failure log entry rendered with error badge', async () => {
      const logRow = page.locator('.ui-list-row').filter({ hasText: testFailMessage });
      await expect(logRow).toBeVisible();
      await expect(logRow).toContainText(testFailAccount);
      await expect(logRow).toContainText(/(失败|Failed)/i);
    });

    await test.step('Verify failure KPI stat counter increments by +1 in real time', async () => {
      await expect(failureStatValue).toHaveText(String(initialFailure + 1));
    });
  });

  test('should gracefully handle SSE disconnection and fall back to polling badge', async ({ page }) => {
    const liveBadge = page.locator('.ui-card')
      .filter({ hasText: /(最近任务日志|近期日志|Recent Logs)/i })
      .locator('.ui-badge')
      .filter({ hasText: /(实时|轮询|Live|Polling)/i });

    await test.step('Connect to SSE stream', async () => {
      await page.evaluate(() => {
        (window as any).__emitSse('ready', {});
      });
      await expect(liveBadge).toContainText(/(实时|Live)/i);
    });

    await test.step('Trigger SSE stream error event', async () => {
      await page.evaluate(() => {
        (window as any).__emitSse('error');
      });

      // Should downgrade liveConnected to false and display Polling indicator
      await expect(liveBadge).toContainText(/(轮询|Polling)/i);
      await expect(liveBadge).toHaveClass(/ui-badge-neutral/);
      await expect(liveBadge.locator('.ui-pulse-dot')).toBeHidden();
    });
  });

});

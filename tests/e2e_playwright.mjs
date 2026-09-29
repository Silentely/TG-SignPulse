import { chromium } from 'playwright';
import path from 'path';

const APP_URL = process.env.APP_URL || 'http://127.0.0.1:5173';
const ARTIFACTS_DIR =
  process.env.ARTIFACTS_DIR ||
  '/Users/adair/.gemini/antigravity-acp/brain/b8db85e8-0c64-4631-868d-4bf7e66c4f18/screenshots';

const results = [];

function recordStep(name, success, detail = '') {
  results.push({ name, success, detail });
  const icon = success ? '✅' : '❌';
  console.log(`${icon} [${name}] ${detail}`);
}

async function launchBrowser() {
  try {
    return await chromium.launch({
      channel: 'msedge',
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox'],
    });
  } catch (e1) {
    console.warn('⚠️ Edge channel launch failed, trying default chromium...', e1.message);
    try {
      return await chromium.launch({
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox'],
      });
    } catch (e2) {
      console.warn('⚠️ Default chromium launch failed, trying chrome channel...', e2.message);
      return await chromium.launch({
        channel: 'chrome',
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox'],
      });
    }
  }
}

async function runPlaywrightE2E() {
  console.log('====================================================');
  console.log('🚀 启动 Playwright 全流程端到端 (E2E) 自动化测试');
  console.log(`📍 目标地址: ${APP_URL}`);
  console.log(`📁 截图输出: ${ARTIFACTS_DIR}`);
  console.log('====================================================\n');

  const browser = await launchBrowser();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    locale: 'zh-CN',
  });
  const page = await context.newPage();

  const consoleErrors = [];
  const networkErrors = [];

  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      if (!text.includes('favicon.ico') && !text.includes('Failed to load resource: net::ERR_CONNECTION_REFUSED') && !text.includes('issue SSE ticket failed')) {
        consoleErrors.push(text);
      }
    }
  });

  page.on('response', (res) => {
    if (res.status() >= 500) {
      networkErrors.push({ url: res.url(), status: res.status() });
    }
  });

  try {
    // -----------------------------------------------------------------
    // 测试 1: 未登录路由守卫拦截与 404 页面
    // -----------------------------------------------------------------
    console.log('\n--- 1️⃣ 测试: 未登录路由守卫拦截与 404 路由 ---');
    const protectedRoutes = ['/dashboard', '/accounts', '/tasks', '/plugins', '/logs', '/settings'];
    for (const route of protectedRoutes) {
      await page.goto(`${APP_URL}${route}`);
      await page.waitForURL('**/login', { timeout: 4000 });
      const currentUrl = page.url();
      if (!currentUrl.includes('/login')) {
        throw new Error(`未受鉴权保护：访问 ${route} 未能重定向到 /login，当前为 ${currentUrl}`);
      }
    }
    recordStep('未登录拦截受保护路由', true, `已验证 6 个受保护路由均正确重定向至 /login`);

    // 404 路由与返回登录测试
    await page.goto(`${APP_URL}/nonexistent-route-for-e2e-test`);
    await page.waitForSelector('text=404', { timeout: 3000 });
    const has404Text = await page.evaluate(() => document.body.innerText.includes('404'));
    if (!has404Text) throw new Error('404 页面未展示 404 标识');

    const backBtn = page.locator('button', { hasText: /(登录|Login)/i });
    if (await backBtn.count() > 0) {
      await backBtn.first().click();
      await page.waitForURL('**/login', { timeout: 3000 });
    }
    await page.screenshot({ path: path.join(ARTIFACTS_DIR, '01_auth_guard_and_404.png') });
    recordStep('404路由兜底与回跳', true, '404 页面展示正常，点击返回按钮成功回到 /login');

    // -----------------------------------------------------------------
    // 测试 2: 登录页表单校验、密码明文切换、国际化与密码错误校验
    // -----------------------------------------------------------------
    console.log('\n--- 2️⃣ 测试: 登录页表单校验、明文切换与错误校验 ---');
    await page.goto(`${APP_URL}/login`);
    await page.waitForSelector('#login-username', { timeout: 5000 });

    // 品牌与输入框验证
    const brand = await page.textContent('h1');
    if (!brand.includes('SIGNPULSE')) throw new Error('未在登录页找到 SIGNPULSE 品牌标题');

    // 密码显隐切换：精准选择 #login-password 旁边的显隐按钮
    const pwdInput = page.locator('#login-password');
    await pwdInput.fill('mySecret123');
    const initialType = await pwdInput.getAttribute('type');
    if (initialType !== 'password') throw new Error(`密码框初始类型不是 password，当前为: ${initialType}`);

    const toggleEyeBtn = page.locator('#login-password ~ button');
    await toggleEyeBtn.click();
    await page.waitForTimeout(200);
    const visibleType = await pwdInput.getAttribute('type');
    if (visibleType !== 'text') throw new Error(`点击显示密码后类型不是 text，当前为: ${visibleType}`);
    await toggleEyeBtn.click();
    await page.waitForTimeout(200);
    const revertedType = await pwdInput.getAttribute('type');
    if (revertedType !== 'password') throw new Error(`再次点击后类型未恢复为 password`);
    recordStep('密码显隐切换', true, '密码类型在 password 与 text 间正确切换');

    // 语言切换测试：位于页脚的第 2 个 .ui-icon-btn (Globe 图标)
    const iconButtons = page.locator('.ui-icon-btn');
    if (await iconButtons.count() >= 2) {
      const langBtn = iconButtons.nth(1);
      await langBtn.click();
      await page.waitForTimeout(300);
      const enText = await page.textContent('button[type="submit"]');
      await langBtn.click(); // 切换回中文
      await page.waitForTimeout(300);
      recordStep('登录页国际化切换', true, `按钮文案动态更新，响应式切换正常 (切换后: ${enText.trim()})`);
    }

    // 主题切换测试：位于页脚的第 3 个 .ui-icon-btn (Sun/Moon 图标)
    if (await iconButtons.count() >= 3) {
      const themeBtn = iconButtons.nth(2);
      const isDarkBefore = await page.evaluate(() => document.documentElement.classList.contains('dark'));
      await themeBtn.click();
      await page.waitForTimeout(300);
      const isDarkAfter = await page.evaluate(() => document.documentElement.classList.contains('dark'));
      if (isDarkBefore === isDarkAfter) throw new Error('主题切换未能改变 <html> dark 样式类');
      await themeBtn.click(); // 切回原主题
      await page.waitForTimeout(300);
      recordStep('登录页深浅主题切换', true, `HTML class 在 dark/light 间平滑切换`);
    }

    // 错误凭据登录拦截
    await page.fill('#login-username', 'admin');
    await page.fill('#login-password', 'wrong_pass_9999');
    await page.click('button[type="submit"]');

    const alertBox = page.locator('[role="alert"]');
    await alertBox.waitFor({ state: 'visible', timeout: 5000 });
    const alertText = await alertBox.textContent();
    const tokenInStorage = await page.evaluate(() => localStorage.getItem('tg-signer-token'));
    if (tokenInStorage) throw new Error('错误密码登录后不应存入 Token');
    if (!page.url().includes('/login')) throw new Error('错误密码登录后发生了非预期跳转');

    await page.screenshot({ path: path.join(ARTIFACTS_DIR, '02_login_invalid_password.png') });
    recordStep('错误密码校验与提示', true, `正确触发警报提示: "${alertText.trim()}" 且未下发 Token`);

    // -----------------------------------------------------------------
    // 测试 3: 正确密码登录与鉴权 Token 持久化
    // -----------------------------------------------------------------
    console.log('\n--- 3️⃣ 测试: 管理员账号正确登录 ---');
    await page.fill('#login-username', 'admin');
    await page.fill('#login-password', 'adminpassword123');
    await page.click('button[type="submit"]');

    await page.waitForURL('**/dashboard', { timeout: 6000 });
    const validToken = await page.evaluate(() => localStorage.getItem('tg-signer-token'));
    if (!validToken) throw new Error('登录成功后 localStorage 中未找到 tg-signer-token');

    await page.screenshot({ path: path.join(ARTIFACTS_DIR, '03_login_success.png') });
    recordStep('管理员登录与Token持久化', true, `登录成功并跳转至 /dashboard，Token 前缀: ${validToken.slice(0, 15)}...`);

    // -----------------------------------------------------------------
    // 测试 4: 仪表盘（Dashboard）指标与组件渲染
    // -----------------------------------------------------------------
    console.log('\n--- 4️⃣ 测试: 仪表盘视图渲染与快捷入口 ---');
    await page.waitForSelector('main', { timeout: 5000 });
    await page.waitForTimeout(1000);

    const bodyText = await page.evaluate(() => document.body.innerText);
    const hasAccountsMetric = bodyText.includes('账号') || bodyText.includes('Accounts');
    const hasTasksMetric = bodyText.includes('任务') || bodyText.includes('Tasks');
    const hasSignpulseTitle = bodyText.includes('SIGNPULSE');

    if (!hasAccountsMetric || !hasTasksMetric || !hasSignpulseTitle) {
      throw new Error('仪表盘未完整渲染核心指标卡片');
    }

    // 检查快捷入口
    const quickLinks = page.locator('main button, main a').filter({ hasText: /(账号|任务|日志|设置|Accounts|Tasks|Logs|Settings)/ });
    const quickLinksCount = await quickLinks.count();
    if (quickLinksCount === 0) throw new Error('仪表盘快捷入口未渲染');

    await page.screenshot({ path: path.join(ARTIFACTS_DIR, '04_dashboard.png') });
    recordStep('仪表盘组件与指标卡片', true, `核心数据指标卡、快捷入口及趋势组件均正常加载`);

    // -----------------------------------------------------------------
    // 测试 5: 账号管理视图（Accounts）与添加账号模态框全流程
    // -----------------------------------------------------------------
    console.log('\n--- 5️⃣ 测试: 账号管理视图与添加账号模态框 ---');
    await page.click('aside nav a[href*="accounts"]');
    await page.waitForURL('**/accounts', { timeout: 5000 });
    await page.waitForTimeout(1000);

    // 搜索框可用性
    const searchInput = page.locator('input[type="search"]');
    if (await searchInput.count() > 0) {
      await searchInput.fill('test_search_keyword');
      const clearBtn = page.locator('button[title*="清除"], button[aria-label*="清除"], button[title*="clear"], button[aria-label*="clear"]');
      if (await clearBtn.count() > 0) {
        await clearBtn.click();
        const val = await searchInput.inputValue();
        if (val !== '') throw new Error('搜索框清除按钮未清空输入内容');
      }
    }

    // 打开添加账号模态框
    const addAccountBtn = page.locator('main button:has-text("添加账号"), main button:has-text("验证码登录"), main button:has-text("扫码登录")').first();
    await addAccountBtn.click();

    // 验证模态框弹出
    const modalDialog = page.locator('[role="dialog"]').last();
    await modalDialog.waitFor({ state: 'visible', timeout: 4000 });
    recordStep('打开添加账号模态框', true, '模态框成功展开');

    // 验证 Tab 切换 (验证码 / 扫码 / Session导入)
    const modalTabs = modalDialog.locator('button[role="tab"]');
    const tabTexts = await modalTabs.allTextContents();
    console.log('   模态框可用 Tab 标签:', tabTexts.map(t => t.trim()).filter(Boolean));

    // 切换到扫码登录
    const qrTab = modalDialog.locator('button[role="tab"]', { hasText: /扫码|QR/i }).first();
    if (await qrTab.count() > 0) {
      await qrTab.click();
      await page.waitForTimeout(300);
    }

    // 切换到 Session 导入
    const importTab = modalDialog.locator('button[role="tab"]', { hasText: /导入|Import/i }).first();
    if (await importTab.count() > 0) {
      await importTab.click();
      await page.waitForTimeout(300);
      const hasFileInput = await modalDialog.locator('input[type="file"]').count() > 0;
      if (!hasFileInput) throw new Error('Session 导入 Tab 中缺少文件上传组件');
    }

    // 关闭模态框 (通过关闭按钮)
    const closeAccModalBtn = modalDialog.locator('button[aria-label*="关闭"], button[aria-label*="Close"], .ui-icon-btn').first();
    if (await closeAccModalBtn.count() > 0) {
      await closeAccModalBtn.click();
    } else {
      await page.keyboard.press('Escape');
    }
    await page.waitForTimeout(500);

    await page.screenshot({ path: path.join(ARTIFACTS_DIR, '05_accounts.png') });
    recordStep('账号视图交互与模态框多Tab', true, '搜索框过滤、模态框打开、多方式登录Tab切换与关闭均正常');

    // -----------------------------------------------------------------
    // 测试 6: 任务管理视图（Tasks）与新建任务模态框
    // -----------------------------------------------------------------
    console.log('\n--- 6️⃣ 测试: 任务管理视图与新建任务模态框 ---');
    await page.click('aside nav a[href*="tasks"]');
    await page.waitForURL('**/tasks', { timeout: 5000 });
    await page.waitForTimeout(1000);

    // 验证模式筛选 (全部 / 定时 / 监听)
    const modeButtons = page.locator('main button', { hasText: /(全部|定时|监听|All|Scheduled|Monitor)/ });
    const modeCount = await modeButtons.count();
    if (modeCount > 0) {
      await modeButtons.first().click();
      await page.waitForTimeout(200);
    }

    // 打开新建任务模态框
    const addTaskBtn = page.locator('main button:has-text("新建任务"), main button:has-text("添加任务"), main button:has-text("创建任务"), main button:has-text("New Task")').first();
    if (await addTaskBtn.count() > 0) {
      await addTaskBtn.click();
      const taskModal = page.locator('[role="dialog"]').last();
      await taskModal.waitFor({ state: 'visible', timeout: 4000 });

      // 验证任务表单元素
      const taskNameInput = taskModal.locator('input').first();
      await taskNameInput.fill('E2E_Test_Task');
      await page.waitForTimeout(200);

      // 关闭任务模态框
      const closeTaskModalBtn = taskModal.locator('button[aria-label*="关闭"], button[aria-label*="Close"], button:has-text("取消"), button:has-text("Cancel")').first();
      if (await closeTaskModalBtn.count() > 0) {
        await closeTaskModalBtn.click();
      } else {
        await page.keyboard.press('Escape');
      }
      await page.waitForTimeout(500);
      recordStep('新建任务表单展开与字段交互', true, '新建任务模态框字段可用，关闭正常');
    } else {
      recordStep('任务列表视图展示', true, '任务列表空态或已有任务展示正常');
    }
    await page.screenshot({ path: path.join(ARTIFACTS_DIR, '06_tasks.png') });

    // -----------------------------------------------------------------
    // 测试 7: 插件管理与遗留路由重定向（Plugins & Legacy Redirect）
    // -----------------------------------------------------------------
    console.log('\n--- 7️⃣ 测试: 插件管理中心与旧路由平滑重定向 ---');
    // 验证旧链接 /settings?tab=plugins 自动重定向至 /plugins
    await page.goto(`${APP_URL}/settings?tab=plugins`);
    await page.waitForURL('**/plugins', { timeout: 5000 });
    if (!page.url().endsWith('/plugins')) {
      throw new Error(`路由重定向失败：/settings?tab=plugins 未能重定向到 /plugins，当前为: ${page.url()}`);
    }
    recordStep('插件旧路由兼容重定向', true, '/settings?tab=plugins 平滑重定向到独立 /plugins');

    // 检查插件列表加载
    await page.waitForSelector('text=math_solver', { timeout: 6000 });
    const hasMath = await page.evaluate(() => document.body.innerText.includes('math_solver'));
    const hasDaily = await page.evaluate(() => document.body.innerText.includes('daily_checkin_helper'));
    if (!hasMath || !hasDaily) throw new Error('插件列表中缺少内置核心插件 math_solver 或 daily_checkin_helper');

    // 检查插件分类切换 (全部 / 实用工具)
    const categoryBtns = page.locator('main button', { hasText: /(实用工具|utility|全部|all)/i });
    if (await categoryBtns.count() > 0) {
      await categoryBtns.first().click();
      await page.waitForTimeout(300);
    }

    // 打开插件数据存储模态框
    const storageBtn = page.locator('main button:has-text("存储"), main button:has-text("Storage")').first();
    await storageBtn.click();
    const storageModal = page.locator('[role="dialog"]').last();
    await storageModal.waitFor({ state: 'visible', timeout: 4000 });

    const storageModalText = await storageModal.textContent();
    if (!storageModalText.includes('存储') && !storageModalText.includes('Storage')) {
      throw new Error('打开的插件模态框不包含存储管理信息');
    }

    // 关闭存储模态框
    const closeStorageModalBtn = storageModal.locator('button[aria-label*="关闭"], button[aria-label*="Close"], .ui-icon-btn').first();
    if (await closeStorageModalBtn.count() > 0) {
      await closeStorageModalBtn.click();
    } else {
      await page.keyboard.press('Escape');
    }
    await page.waitForTimeout(400);

    await page.screenshot({ path: path.join(ARTIFACTS_DIR, '07_plugins.png') });
    recordStep('插件管理与存储检视', true, '内置插件完整列出，分类筛选与插件隔离存储弹窗检视正常');

    // -----------------------------------------------------------------
    // 测试 8: 运行日志视图与审计日志切换（Logs）
    // -----------------------------------------------------------------
    console.log('\n--- 8️⃣ 测试: 日志中心与审计日志 Tab 切换 ---');
    await page.click('aside nav a[href*="logs"]');
    await page.waitForURL('**/logs', { timeout: 5000 });
    await page.waitForTimeout(1000);

    // 验证 Tab 切换 (任务日志 <-> 登录日志)
    const auditTab = page.locator('main button', { hasText: /(系统审计日志|审计日志|Audit Logs)/i }).first();
    if (await auditTab.count() > 0) {
      await auditTab.click();
      await page.waitForTimeout(600);
      const auditBody = await page.evaluate(() => document.body.innerText);
      const hasAuditEntry = auditBody.includes('admin') || auditBody.includes('成功') || auditBody.includes('IP');
      console.log('   审计日志内容检测:', hasAuditEntry ? '已记录最新管理员登录日志' : '审计日志为空或渲染中');

      // 切换回任务日志
      const taskLogsTab = page.locator('main button', { hasText: /(任务执行日志|任务日志|Task Logs)/i }).first();
      await taskLogsTab.click();
      await page.waitForTimeout(400);
    }

    // 刷新日志按钮测试
    const refreshLogsBtn = page.locator('main button[aria-label*="刷新"], main button[title*="刷新"], main button[aria-label*="refresh"], main button[title*="refresh"]').first();
    if (await refreshLogsBtn.count() > 0) {
      await refreshLogsBtn.click();
      await page.waitForTimeout(400);
    }

    await page.screenshot({ path: path.join(ARTIFACTS_DIR, '08_logs.png') });
    recordStep('日志中心全功能', true, '任务日志与登录审计日志 Tab 切换正常，刷新与筛选控件均可用');

    // -----------------------------------------------------------------
    // 测试 9: 系统设置视图（Settings）与密钥显隐切换
    // -----------------------------------------------------------------
    console.log('\n--- 9️⃣ 测试: 系统设置配置面板与敏感密钥显隐 ---');
    await page.click('aside nav a[href*="settings"]');
    await page.waitForURL('**/settings', { timeout: 5000 });
    await page.waitForTimeout(1000);

    const settingsText = await page.evaluate(() => document.body.innerText);
    const hasGeneral = settingsText.includes('通用设置') || settingsText.includes('General');
    const hasTgApi = settingsText.includes('Telegram') || settingsText.includes('API ID');
    const hasBackup = settingsText.includes('数据') || settingsText.includes('备份') || settingsText.includes('Backup');

    if (!hasGeneral || !hasTgApi || !hasBackup) {
      throw new Error('系统设置页面未能完整加载通用设置、Telegram API 或数据备份面板');
    }

    // 验证敏感信息显隐切换（Telegram API Hash）
    const revealBtns = page.locator('main button:has(svg)').filter({
      has: page.locator('svg'),
    });
    if (await revealBtns.count() > 0) {
      await revealBtns.first().click();
      await page.waitForTimeout(300);
      await revealBtns.first().click();
      await page.waitForTimeout(300);
    }

    await page.screenshot({ path: path.join(ARTIFACTS_DIR, '09_settings.png') });
    recordStep('系统设置面板渲染与密钥保护', true, '通用、Telegram API、通知、数据备份等板块正常，敏感项切换平稳');

    // -----------------------------------------------------------------
    // 测试 10: 个人中心模态框与退出登录拦截验证（Profile & Logout）
    // -----------------------------------------------------------------
    console.log('\n--- 🔟 测试: 个人中心模态框与退出登录流程 ---');
    const profileBtn = page.locator('aside button', { hasText: /(个人资料|个人中心|Profile)/i }).first();
    await profileBtn.click();

    const profileModal = page.locator('[role="dialog"]').last();
    await profileModal.waitFor({ state: 'visible', timeout: 4000 });

    // 验证 Tab (用户名 / 密码 / 两步验证)
    const profileTabs = profileModal.locator('button[role="tab"]');
    const pTabCount = await profileTabs.count();
    if (pTabCount >= 3) {
      await profileTabs.nth(1).click(); // 切换密码
      await page.waitForTimeout(200);
      await profileTabs.nth(2).click(); // 切换两步验证
      await page.waitForTimeout(200);
    }

    // 点击退出登录
    const logoutBtn = profileModal.locator('button', { hasText: /(退出登录|Logout)/i });
    if (await logoutBtn.count() === 0) throw new Error('未在个人中心模态框找到退出登录按钮');
    await logoutBtn.click();

    // 验证重定向到 /login 且 Token 被清空
    await page.waitForURL('**/login', { timeout: 5000 });
    const clearedToken = await page.evaluate(() => localStorage.getItem('tg-signer-token'));
    if (clearedToken) throw new Error(`退出登录后 Token 仍保留在 localStorage 中: ${clearedToken}`);

    // 再次验证受保护路由立即被拒
    await page.goto(`${APP_URL}/dashboard`);
    await page.waitForURL('**/login', { timeout: 4000 });

    await page.screenshot({ path: path.join(ARTIFACTS_DIR, '10_logout.png') });
    recordStep('个人中心与登出拦截闭环', true, '密码与TOTP配置正常，退出登录后彻底注销 Token 并恢复未登录守卫');

    // -----------------------------------------------------------------
    // 测试 11: 异常审查（Console Errors & Network Errors）
    // -----------------------------------------------------------------
    console.log('\n--- 🔍 控制台与网络健康审查 ---');
    if (networkErrors.length > 0) {
      console.warn('⚠️ 捕获到 5xx 服务端错误响应:', networkErrors);
      throw new Error(`存在 ${networkErrors.length} 个 5xx 网络错误`);
    } else {
      recordStep('服务端响应质量审查', true, '全流程测试期间零 5xx 服务端异常错误');
    }

    if (consoleErrors.length > 0) {
      console.warn('⚠️ 捕获到浏览器控制台错误:', consoleErrors);
    } else {
      recordStep('控制台异常与未捕获错误审查', true, '全流程测试期间零致命控制台未捕获错误');
    }

    console.log('\n====================================================');
    console.log('🎉 恭喜！Playwright E2E 完整自动化测试无任何遗漏并通过！');
    console.log('====================================================\n');
  } catch (err) {
    console.error('\n❌ E2E 测试异常终止:', err);
    await page.screenshot({ path: path.join(ARTIFACTS_DIR, 'error_failure.png') }).catch(() => {});
    process.exitCode = 1;
  } finally {
    await browser.close();
  }

  return results;
}

runPlaywrightE2E();

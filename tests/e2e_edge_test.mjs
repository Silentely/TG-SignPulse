import {
  newPage,
  navigate,
  evaluate,
  fill,
  click,
  wait,
  screenshot,
  captureConsole,
  captureResponses,
  DEFAULT_PORT,
} from '/Users/adair/.gemini/config/skills/edge-cdp-test/scripts/cdp.mjs';

const APP_URL = 'http://127.0.0.1:5173';
const ARTIFACTS_DIR = '/Users/adair/.gemini/antigravity-acp/brain/9541c764-fc6d-462e-9231-449fa59df019';

async function runE2ETests() {
  console.log('🚀 启动 Edge CDP E2E 端到端测试...');
  const { cdp } = await newPage(DEFAULT_PORT);

  const consoleCap = await captureConsole(cdp);
  const responsesCap = await captureResponses(cdp);

  try {
    // ----------------------------------------------------
    // 测试 1: 登录页面渲染与品牌标识
    // ----------------------------------------------------
    console.log('1️⃣ 测试: 访问登录页面与品牌验证');
    await navigate(cdp, `${APP_URL}/login`);
    await wait(800);

    const title = await evaluate(cdp, 'document.title');
    console.log(`   页面标题: "${title}"`);

    const hasUsernameInput = await evaluate(cdp, '!!document.querySelector("#login-username")');
    const hasPasswordInput = await evaluate(cdp, '!!document.querySelector("#login-password")');
    const brandText = await evaluate(cdp, 'document.body.innerText.includes("SIGNPULSE")');

    if (!hasUsernameInput || !hasPasswordInput) {
      throw new Error('未在页面中找到登录输入框 (#login-username, #login-password)');
    }
    if (!brandText) {
      throw new Error('未在页面中检测到 SIGNPULSE 品牌字样');
    }

    const loginShotPath = `${ARTIFACTS_DIR}/e2e_login.png`;
    await screenshot(cdp, loginShotPath);
    console.log(`   ✅ 登录页面加载成功，截图已保存: ${loginShotPath}`);

    // ----------------------------------------------------
    // 测试 2: 管理员登录与鉴权状态持久化
    // ----------------------------------------------------
    console.log('2️⃣ 测试: 执行表单登录');
    await fill(cdp, '#login-username', 'admin');
    await fill(cdp, '#login-password', 'adminpassword123');
    await wait(200);

    await click(cdp, 'form button[type="submit"]');
    console.log('   已提交登录表单，等待跳转与 Token 颁发...');

    // 等待 localStorage 写入 token
    let token = null;
    for (let i = 0; i < 20; i++) {
      await wait(300);
      token = await evaluate(cdp, 'localStorage.getItem("tg-signer-token")');
      if (token) break;
    }

    if (!token) {
      const errText = await evaluate(cdp, 'document.querySelector(".text-red-500, .ui-badge-danger")?.textContent');
      throw new Error(`登录失败，未获取到 Token。页面错误: ${errText || '无'}`);
    }
    console.log('   ✅ 登录鉴权成功，Token 已注入');

    // ----------------------------------------------------
    // 测试 3: 访问系统设置 -> 插件管理面板
    // ----------------------------------------------------
    console.log('3️⃣ 测试: 访问系统设置并加载插件列表');
    await navigate(cdp, `${APP_URL}/settings`);
    await wait(1500);

    // 等待插件卡片渲染
    let pluginsLoaded = false;
    for (let i = 0; i < 25; i++) {
      pluginsLoaded = await evaluate(cdp, `
        document.body.innerText.includes("math_solver") ||
        document.body.innerText.includes("daily_checkin_helper")
      `);
      if (pluginsLoaded) break;
      await wait(300);
    }

    if (!pluginsLoaded) {
      throw new Error('设置页面中未在预期时间内渲染插件列表（未检测到 math_solver 或 daily_checkin_helper）');
    }

    // 验证分类标签与元数据呈现
    const metadataCheck = await evaluate(cdp, `(() => {
      const text = document.body.innerText;
      return {
        hasUtilityCategory: text.includes("utility") || text.includes("实用工具"),
        hasMathSolver: text.includes("math_solver"),
        hasDailyHelper: text.includes("daily_checkin_helper"),
        hasStorageButton: Array.from(document.querySelectorAll("button")).some(b => 
          b.textContent.includes("存储") || b.textContent.includes("Storage") || (b.title && b.title.includes("存储"))
        )
      };
    })()`);

    console.log('   插件面板元数据检查:', JSON.stringify(metadataCheck));
    if (!metadataCheck.hasMathSolver) throw new Error('插件列表中缺失 math_solver');
    if (!metadataCheck.hasStorageButton) throw new Error('插件卡片中缺失数据存储按钮');

    const pluginsShotPath = `${ARTIFACTS_DIR}/e2e_plugins.png`;
    await screenshot(cdp, pluginsShotPath);
    console.log(`   ✅ 插件管理面板加载正常，截图已保存: ${pluginsShotPath}`);

    // ----------------------------------------------------
    // 测试 4: 打开插件存储检查与清理模态弹窗
    // ----------------------------------------------------
    console.log('4️⃣ 测试: 打开数据存储模态框并查看键值与命名空间');
    
    // 点击数据存储按钮
    const storageBtnClicked = await evaluate(cdp, `(() => {
      const btns = Array.from(document.querySelectorAll("button"));
      const target = btns.find(b => 
        b.textContent.includes("存储") || b.textContent.includes("Storage") || (b.title && b.title.includes("存储"))
      );
      if (target) {
        target.click();
        return true;
      }
      return false;
    })()`);

    if (!storageBtnClicked) {
      throw new Error('未能触发数据存储按钮点击');
    }

    // 等待弹窗弹出
    let modalOpened = false;
    for (let i = 0; i < 20; i++) {
      await wait(300);
      modalOpened = await evaluate(cdp, `(() => {
        const modal = document.querySelector('[role="dialog"], .fixed.inset-0');
        return !!modal && (modal.textContent.includes("存储") || modal.textContent.includes("Storage"));
      })()`);
      if (modalOpened) break;
    }

    if (!modalOpened) {
      throw new Error('点击存储按钮后模态弹窗未在预期时间内展示');
    }

    await wait(600);
    const storageShotPath = `${ARTIFACTS_DIR}/e2e_storage_modal.png`;
    await screenshot(cdp, storageShotPath);
    console.log(`   ✅ 存储管理弹窗渲染成功，截图已保存: ${storageShotPath}`);

    // 关闭弹窗（查找关闭按钮或按 Esc）
    await evaluate(cdp, `(() => {
      const closeBtn = document.querySelector('[role="dialog"] button, .fixed.inset-0 button');
      if (closeBtn) closeBtn.click();
    })()`);
    await wait(300);

    // ----------------------------------------------------
    // 测试 5: 控制台错误与异常检测
    // ----------------------------------------------------
    console.log('5️⃣ 测试: 控制台与网络质量审查');
    const realErrors = consoleCap.errors.filter(e => {
      const msg = typeof e === 'string' ? e : JSON.stringify(e);
      // 忽略可能的 favicon 404 或已知第三方非致命警告
      return !msg.includes('favicon.ico') && !msg.includes('PWA');
    });

    if (realErrors.length > 0) {
      console.warn(`   ⚠️ 检测到 ${realErrors.length} 条控制台错误:`, realErrors);
    } else {
      console.log('   ✅ 全流程运行期间无严重控制台异常');
    }

    console.log('\n🎉 [E2E 测试全部顺利通过] 🎉\n');
  } finally {
    cdp.close();
  }
}

runE2ETests().catch((err) => {
  console.error('❌ E2E 测试失败:', err);
  process.exit(1);
});

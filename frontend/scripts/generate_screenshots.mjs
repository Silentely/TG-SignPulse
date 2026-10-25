import { createServer } from 'vite'
import { chromium } from 'playwright'
import path from 'path'
import { fileURLToPath } from 'url'
import fs from 'fs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(__dirname, '..')
const rootDir = path.resolve(frontendDir, '..')
const outputDir = path.resolve(rootDir, 'docs/public/screenshots')

const MOCK_JWT = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MjUzNDA2MDgwMDAwfQ.dGctc2lnbnB1bHNlLXRlc3Qtc2lnbmF0dXJl'

async function setupApiMocks(page) {
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    if (!url.pathname.startsWith('/api/')) {
      return route.continue()
    }

    const path = url.pathname.replace(/^\/api/, '')
    const method = route.request().method()

    // 1. SSE Events
    if (path === '/events/sign-history' || path.startsWith('/events/stream')) {
      return route.fulfill({
        status: 200,
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Connection': 'keep-alive'
        },
        body: ': heartbeat\n\n'
      })
    }
    if (path === '/events/ticket' || path === '/stream-tickets') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ticket: 'mock-ticket-token-12345' })
      })
    }

    // 2. Accounts
    if (path === '/accounts' && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          accounts: [
            {
              name: 'Alpha_Signer',
              session_file: 'Alpha_Signer.session',
              exists: true,
              size: 131072,
              remark: '主号 · 每日打卡与官方核心频道',
              proxy: 'socks5://127.0.0.1:10808',
              status: 'connected',
              status_message: '在线正常 (Ping: 38ms)',
              status_code: '200',
              status_checked_at: new Date().toISOString(),
              needs_relogin: false,
              tags: ['主号', '每日打卡', '香港专线'],
              device_family: 'desktop',
              device_profile: {
                app_version: '5.4.1 x64',
                device_model: 'MacBookPro18,1',
                system_version: 'macOS 15.0'
              }
            },
            {
              name: 'Beta_Crypto',
              session_file: 'Beta_Crypto.session',
              exists: true,
              size: 98304,
              remark: '交易 · VIP 机器人与 AI 验证码答题',
              proxy: 'socks5://127.0.0.1:10809',
              status: 'connected',
              status_message: '在线正常 (Ping: 52ms)',
              status_code: '200',
              status_checked_at: new Date().toISOString(),
              needs_relogin: false,
              tags: ['VIP答题', '新加坡节点'],
              device_family: 'android',
              device_profile: {
                app_version: '10.9.1',
                device_model: 'Google Pixel 8 Pro',
                system_version: 'Android 14'
              }
            },
            {
              name: 'Gamma_Worker',
              session_file: 'Gamma_Worker.session',
              exists: true,
              size: 65536,
              remark: '测试机 · 节点巡检与关键词实时监听',
              proxy: null,
              status: 'connected',
              status_message: '在线正常 (Ping: 45ms)',
              status_code: '200',
              status_checked_at: new Date().toISOString(),
              needs_relogin: false,
              tags: ['监听告警', '直连', '骰子互动'],
              device_family: 'desktop',
              device_profile: {
                app_version: '5.2.0 x64',
                device_model: 'Windows PC',
                system_version: 'Windows 11'
              }
            }
          ],
          total: 3
        })
      })
    }

    if (path.startsWith('/accounts/logs/recent')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            time: new Date(Date.now() - 1000 * 30).toISOString(),
            created_at: new Date(Date.now() - 1000 * 30).toISOString(),
            account: 'Beta_Crypto',
            task: 'VIP群打卡 & AI视觉答题',
            status: 'info',
            success: true,
            text: 'AI OCR 解析图片成功: 计算题 17 + 8 = 25，正在点击对应选项按钮 [25]',
            message: 'AI OCR 解析图片成功: 计算题 17 + 8 = 25，正在点击对应选项按钮 [25]'
          },
          {
            time: new Date(Date.now() - 1000 * 180).toISOString(),
            created_at: new Date(Date.now() - 1000 * 180).toISOString(),
            account: 'Alpha_Signer',
            task: '重要频道关键词实时监听',
            status: 'success',
            success: true,
            text: '频道 @AlphaNewsChannel 命中关键词 (airdrop)，已成功推送通知',
            message: '频道 @AlphaNewsChannel 命中关键词 (airdrop)，已成功推送通知'
          },
          {
            time: new Date(Date.now() - 1000 * 600).toISOString(),
            created_at: new Date(Date.now() - 1000 * 600).toISOString(),
            account: 'Alpha_Signer',
            task: '每日自动签到 & 领金币',
            status: 'success',
            success: true,
            text: '签到成功！获得金币 +50，当前连续签到 18 天',
            message: '签到成功！获得金币 +50，当前连续签到 18 天'
          },
          {
            time: new Date(Date.now() - 1000 * 750).toISOString(),
            created_at: new Date(Date.now() - 1000 * 750).toISOString(),
            account: 'Beta_Crypto',
            task: '每日自动签到 & 领金币',
            status: 'success',
            success: true,
            text: '签到成功，响应延迟 1.2s',
            message: '签到成功，响应延迟 1.2s'
          },
          {
            time: new Date(Date.now() - 1000 * 3600).toISOString(),
            created_at: new Date(Date.now() - 1000 * 3600).toISOString(),
            account: 'Gamma_Worker',
            task: '节点保活与骰子博弈',
            status: 'success',
            success: true,
            text: '已向 @LuckyDiceBot 发送 🎲，掷出 6 点，日常互动完成',
            message: '已向 @LuckyDiceBot 发送 🎲，掷出 6 点，日常互动完成'
          }
        ])
      })
    }

    if (path.startsWith('/accounts/status') || path === '/accounts/status-check/jobs') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ jobs: [], results: [] })
      })
    }

    if (path.includes('/devices')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          devices: [
            {
              auth_hash: 'auth_1',
              device_model: 'MacBookPro18,1',
              platform: 'macOS',
              system_version: 'macOS 15.0',
              app_version: '5.4.1 x64',
              ip: '202.175.42.10',
              country: 'Hong Kong (香港专线)',
              date_active: Math.floor(Date.now() / 1000),
              date_created: Math.floor(Date.now() / 1000) - 86400 * 30,
              is_current: true,
              is_official_app: true
            },
            {
              auth_hash: 'auth_2',
              device_model: 'iPhone 15 Pro',
              platform: 'iOS',
              system_version: 'iOS 18.1',
              app_version: '10.8.2',
              ip: '202.175.42.11',
              country: 'Hong Kong',
              date_active: Math.floor(Date.now() / 1000) - 3600 * 4,
              date_created: Math.floor(Date.now() / 1000) - 86400 * 60,
              is_current: false,
              is_official_app: true
            },
            {
              auth_hash: 'auth_3',
              device_model: 'Google Pixel 8',
              platform: 'Android',
              system_version: 'Android 14',
              app_version: '10.5.0',
              ip: '103.21.244.15',
              country: 'Singapore',
              date_active: Math.floor(Date.now() / 1000) - 86400 * 5,
              date_created: Math.floor(Date.now() / 1000) - 86400 * 90,
              is_current: false,
              is_official_app: true
            }
          ],
          total: 3
        })
      })
    }

    if (path.includes('/official-messages')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          messages: [
            {
              id: 101,
              date: new Date(Date.now() - 1000 * 3600 * 2).toISOString(),
              message: 'Login code: 74921. Do not give this code to anyone, even if they say they are from Telegram!'
            }
          ],
          total: 1
        })
      })
    }

    if (path.includes('/folders')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          folders: [
            { id: 1, title: '常用频道' },
            { id: 2, title: '签到机器人' },
            { id: 3, title: '加密交流群' }
          ]
        })
      })
    }

    // 3. Sign Tasks & Chats
    if (path.includes('/chats/') && path.includes('/search')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          chats: [
            { id: 1001234567, name: 'DailyBonusBot', title: '每日金币机器人', type: 'bot' },
            { id: 1009876543, name: 'CryptoVipBot', title: 'Crypto VIP 机器人', type: 'bot' },
            { id: 1005556667, name: 'AlphaNewsChannel', title: 'Alpha News 官方频道', type: 'channel' },
            { id: 1004443322, name: 'LuckyDiceBot', title: '幸运骰子娱乐群', type: 'group' }
          ],
          total: 4
        })
      })
    }

    if (path.includes('/chats/')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 1001234567, name: 'DailyBonusBot', title: '每日金币机器人', type: 'bot' },
          { id: 1009876543, name: 'CryptoVipBot', title: 'Crypto VIP 机器人', type: 'bot' },
          { id: 1005556667, name: 'AlphaNewsChannel', title: 'Alpha News 官方频道', type: 'channel' },
          { id: 1004443322, name: 'LuckyDiceBot', title: '幸运骰子娱乐群', type: 'group' }
        ])
      })
    }

    if (path === '/sign-tasks' && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            name: 'VIP群打卡 & AI视觉答题',
            account_name: 'Beta_Crypto',
            account_names: ['Beta_Crypto'],
            sign_at: '09:00',
            execution_mode: 'fixed',
            random_seconds: 0,
            jitter_seconds: 30,
            sign_interval: 2,
            enabled: true,
            retry_count: 2,
            tags: ['AI视觉验证', 'OCR答题', 'VIP群组'],
            last_run: {
              time: new Date(Date.now() - 1000 * 30).toISOString(),
              success: true,
              message: 'AI OCR 识别验证码成功: 17 + 8 = 25，已选定正确选项'
            },
            chats: [
              {
                chat_id: 1009876543,
                name: '@CryptoVipBot',
                action_interval: 2,
                actions: [
                  { action_type: 'text', content: '/checkin' },
                  { action_type: 'ai_click', content: '识别图片中的计算题并推断正确答案按钮' },
                  { action_type: 'button', content: '确认领奖' }
                ]
              }
            ]
          },
          {
            name: '每日自动签到 & 领金币',
            account_name: 'Alpha_Signer',
            account_names: ['Alpha_Signer', 'Beta_Crypto'],
            sign_at: '08:30',
            execution_mode: 'range',
            range_start: '08:00',
            range_end: '09:30',
            random_seconds: 120,
            jitter_seconds: 60,
            sign_interval: 3,
            enabled: true,
            retry_count: 3,
            tags: ['每日打卡', '多账号轮换', '金币领取'],
            last_run: {
              time: new Date(Date.now() - 1000 * 600).toISOString(),
              success: true,
              message: '签到成功，获得金币 +50，当前连续签到 18 天'
            },
            chats: [
              {
                chat_id: 1001234567,
                name: '@DailyBonusBot',
                action_interval: 3,
                actions: [
                  { action_type: 'text', content: '/sign' },
                  { action_type: 'button', content: '立即签到' },
                  { action_type: 'text', content: '/daily_reward' }
                ]
              }
            ]
          },
          {
            name: '重要频道关键词实时监听',
            account_name: 'Alpha_Signer',
            account_names: ['Alpha_Signer', 'Gamma_Worker'],
            sign_at: '00:00',
            execution_mode: 'listen',
            random_seconds: 0,
            sign_interval: 0,
            enabled: true,
            retry_count: 1,
            tags: ['实时监听', '空投推送', 'Webhook'],
            last_run: {
              time: new Date(Date.now() - 1000 * 180).toISOString(),
              success: true,
              message: '命中关键词 (airdrop)，已成功推送到 Telegram Bot 与 Feishu'
            },
            chats: [
              {
                chat_id: 1005556667,
                name: '@AlphaNewsChannel',
                action_interval: 0,
                actions: [
                  { action_type: 'listen', content: '(airdrop|whitelist|mint|testnet)' }
                ]
              }
            ]
          },
          {
            name: '节点保活与骰子博弈',
            account_name: 'Gamma_Worker',
            account_names: ['Gamma_Worker'],
            sign_at: '12:00',
            execution_mode: 'fixed',
            random_seconds: 180,
            jitter_seconds: 45,
            sign_interval: 5,
            enabled: true,
            retry_count: 2,
            tags: ['日常互动', '保活防封', '趣味博弈'],
            last_run: {
              time: new Date(Date.now() - 1000 * 3600).toISOString(),
              success: true,
              message: '骰子掷出 6 点，日常互动完成'
            },
            chats: [
              {
                chat_id: 1004443322,
                name: '@LuckyDiceBot',
                action_interval: 4,
                actions: [
                  { action_type: 'dice', content: '🎲' }
                ]
              }
            ]
          }
        ])
      })
    }

    if (path === '/sign-tasks/runs/active') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          runs: [
            {
              run_id: 'run_active_1025',
              task_name: 'VIP群打卡 & AI视觉答题',
              account_name: 'Beta_Crypto',
              state: 'running',
              phase: 'running',
              phase_detail: '正在调用 OpenAI 视觉接口识别图形验证码 (17+8)...',
              started_at: new Date(Date.now() - 1000 * 15).toISOString(),
              wait_seconds: 0
            }
          ]
        })
      })
    }

    if (path.includes('/history')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            time: new Date(Date.now() - 1000 * 600).toISOString(),
            success: true,
            message: '签到成功，获得金币 +50，当前连续签到 18 天',
            flow_logs: [
              '[09:00:01] 任务启动，执行账号: Beta_Crypto',
              '[09:00:02] 发送文本指令: /checkin',
              '[09:00:03] 捕获机器人验证码图片 (17 + 8 = ?)',
              '[09:00:04] AI 视觉识别结果: 25，置信度 0.98',
              '[09:00:05] 点击选项按钮 [25]，验证通过！',
              '[09:00:06] 点击按钮 [确认领奖]，日常任务圆满结束'
            ]
          }
        ])
      })
    }

    // 4. Ops & Trends
    if (path.startsWith('/ops/trends')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          days: 7,
          total_runs: 1284,
          total_success: 1266,
          total_failed: 18,
          overall_success_rate: 98.6,
          trends: [
            { date: '10-19', total: 182, success: 180, failed: 2, success_rate: 98.9 },
            { date: '10-20', total: 185, success: 183, failed: 2, success_rate: 98.9 },
            { date: '10-21', total: 180, success: 178, failed: 2, success_rate: 98.8 },
            { date: '10-22', total: 184, success: 181, failed: 3, success_rate: 98.3 },
            { date: '10-23', total: 183, success: 180, failed: 3, success_rate: 98.4 },
            { date: '10-24', total: 186, success: 184, failed: 2, success_rate: 98.9 },
            { date: '10-25', total: 184, success: 180, failed: 4, success_rate: 97.8 }
          ],
          categories: {
            network_timeout: 8,
            button_not_found: 5,
            flood_wait: 3,
            ai_timeout: 2
          }
        })
      })
    }

    if (path === '/ops/scheduled-jobs') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          jobs: [
            {
              id: 'job_1',
              task_name: 'VIP群打卡 & AI视觉答题',
              account_name: 'Beta_Crypto',
              execution_mode: 'fixed',
              next_run_time: new Date(Date.now() + 1000 * 3600 * 13).toISOString()
            },
            {
              id: 'job_2',
              task_name: '每日自动签到 & 领金币',
              account_name: 'Alpha_Signer',
              execution_mode: 'range',
              range_start: '08:00',
              range_end: '09:30',
              next_run_time: new Date(Date.now() + 1000 * 3600 * 12).toISOString()
            },
            {
              id: 'job_3',
              task_name: '节点保活与骰子博弈',
              account_name: 'Gamma_Worker',
              execution_mode: 'fixed',
              next_run_time: new Date(Date.now() + 1000 * 3600 * 3).toISOString()
            }
          ]
        })
      })
    }

    if (path === '/keyword-hits') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              id: 'hit_1',
              task_name: '重要频道关键词实时监听',
              account_name: 'Alpha_Signer',
              chat_id: 1005556667,
              chat_name: 'AlphaNewsChannel',
              keyword: 'airdrop',
              message_text: '🔥 Official Layer2 Airdrop claim portal is now open for testnet participants!',
              created_at: new Date(Date.now() - 1000 * 180).toISOString(),
              actions_taken: 'Bot 推送 + 转发通知'
            },
            {
              id: 'hit_2',
              task_name: '重要频道关键词实时监听',
              account_name: 'Alpha_Signer',
              chat_id: 1005556667,
              chat_name: 'AlphaNewsChannel',
              keyword: 'whitelist',
              message_text: 'Round 2 Whitelist winners announced. Check your address on Github.',
              created_at: new Date(Date.now() - 1000 * 7200).toISOString(),
              actions_taken: 'Bot 推送'
            }
          ],
          total: 2
        })
      })
    }

    if (path === '/ops/version') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          version: 'v2.5.0',
          git_commit: '7b9e1a2',
          build_time: '2026-10-25T00:00:00Z',
          is_latest: true
        })
      })
    }

    if (path === '/ops/backup/status') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          configured: true,
          target: 'auto',
          webdav_url: 'https://dav.jianguoyun.com/dav/backup/tg-signpulse',
          webdav_username: 'ops@signpulse.io',
          last_backup_time: new Date(Date.now() - 1000 * 3600 * 5).toISOString(),
          last_backup_status: 'success',
          last_backup_filename: 'tg-signpulse-backup-20261025-030000.spbak',
          last_backup_size: 2564120,
          total_backups_count: 14,
          auto_backup_enabled: true,
          auto_backup_time: '03:00'
        })
      })
    }

    if (path === '/ops/runtime-status') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          uptime_seconds: 432000,
          scheduler_running: true,
          active_workers: 4,
          queue_size: 0,
          database_mode: 'sqlite_wal'
        })
      })
    }

    if (path === '/ops/memory') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          rss_bytes: 85 * 1024 * 1024,
          vms_bytes: 190 * 1024 * 1024,
          percent: 1.2
        })
      })
    }

    // 5. Config & Settings
    if (path === '/config/settings') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          timezone: 'Asia/Shanghai',
          sign_interval: 3,
          task_timeout: 60,
          task_cooldown: 10,
          max_retries: 3,
          notify_channel: 'telegram',
          bot_token: '7189123456:AAFlk_MOCK_TOKEN_EXAMPLE_TgSignPulse',
          chat_id: '-1001928374650',
          telegram_notify_enabled: true,
          feishu_webhook: 'https://open.feishu.cn/open-apis/bot/v2/hook/mock_token',
          feishu_notify_enabled: true,
          dingtalk_webhook: '',
          dingtalk_notify_enabled: false,
          discord_webhook: 'https://discord.com/api/webhooks/123456789/mock_webhook',
          discord_notify_enabled: true,
          wecom_webhook: '',
          wecom_notify_enabled: false,
          proxy: 'socks5://127.0.0.1:10808',
          keepalive_interval_hours: 12,
          quiet_hours_enabled: true,
          quiet_hours_start: '23:00',
          quiet_hours_end: '07:00'
        })
      })
    }

    if (path === '/config/ai') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          enabled: true,
          base_url: 'https://api.openai.com/v1',
          api_key: 'sk-proj-********************************',
          model: 'gpt-4o-mini',
          timeout: 30,
          max_tokens: 150,
          temperature: 0.2,
          system_prompt: '你是一个 Telegram 自动化验证助手，能够精准识别图形验证码、诗词填空与数学计算题。'
        })
      })
    }

    if (path === '/config/telegram') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          api_id: 20401234,
          api_hash: '1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d',
          device_model: 'MacBookPro18,1',
          system_version: 'macOS 15.0',
          app_version: '5.4.1 x64',
          lang_code: 'zh-hans',
          system_lang_code: 'zh-Hans'
        })
      })
    }

    if (path === '/user/totp/status') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ enabled: true })
      })
    }

    if (path === '/semantic/config') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          enabled: true,
          model: 'gpt-4o-mini',
          confidence_threshold: 0.85
        })
      })
    }

    if (path === '/semantic/suggestions') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([])
      })
    }

    // 6. Logs
    if (path.startsWith('/logs/tasks')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'log_1',
            task_name: 'VIP群打卡 & AI视觉答题',
            account_name: 'Beta_Crypto',
            chat_name: '@CryptoVipBot',
            status: 'success',
            created_at: new Date(Date.now() - 1000 * 30).toISOString(),
            duration_seconds: 3.4,
            summary: 'AI OCR 识别验证码成功: 17 + 8 = 25，已选定正确选项',
            steps_count: 3
          },
          {
            id: 'log_2',
            task_name: '重要频道关键词实时监听',
            account_name: 'Alpha_Signer',
            chat_name: '@AlphaNewsChannel',
            status: 'success',
            created_at: new Date(Date.now() - 1000 * 180).toISOString(),
            duration_seconds: 0.5,
            summary: "命中关键词 'airdrop'，已通过 Telegram Bot 转发推送",
            steps_count: 1
          },
          {
            id: 'log_3',
            task_name: '每日自动签到 & 领金币',
            account_name: 'Alpha_Signer',
            chat_name: '@DailyBonusBot',
            status: 'success',
            created_at: new Date(Date.now() - 1000 * 600).toISOString(),
            duration_seconds: 2.1,
            summary: '签到成功，获得金币 +50，连续签到 18 天',
            steps_count: 3
          },
          {
            id: 'log_4',
            task_name: '每日自动签到 & 领金币',
            account_name: 'Beta_Crypto',
            chat_name: '@DailyBonusBot',
            status: 'success',
            created_at: new Date(Date.now() - 1000 * 750).toISOString(),
            duration_seconds: 1.8,
            summary: '签到完成，耗时 1.8 秒',
            steps_count: 3
          },
          {
            id: 'log_5',
            task_name: '节点保活与骰子博弈',
            account_name: 'Gamma_Worker',
            chat_name: '@LuckyDiceBot',
            status: 'success',
            created_at: new Date(Date.now() - 1000 * 3600).toISOString(),
            duration_seconds: 4.2,
            summary: '骰子掷出 6 点，日常互动成功完成',
            steps_count: 1
          }
        ])
      })
    }

    if (path.startsWith('/logs/login')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'login_1',
            username: 'admin',
            ip: '192.168.1.50',
            user_agent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            status: 'success',
            created_at: new Date(Date.now() - 1000 * 3600 * 2).toISOString()
          }
        ])
      })
    }

    if (path === '/plugins') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([])
      })
    }

    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({})
    })
  })
}

async function main() {
  console.log('Starting Vite server for frontend at port 5199...')
  const server = await createServer({
    root: frontendDir,
    server: {
      port: 5199,
      host: '127.0.0.1'
    }
  })
  await server.listen()
  console.log('Vite server running at http://127.0.0.1:5199')

  const browser = await chromium.launch({
    executablePath: '/usr/bin/chromium',
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  })

  // Desktop context (1440x900 @ 2x deviceScaleFactor)
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    colorScheme: 'dark',
    locale: 'zh-CN'
  })

  const page = await context.newPage()

  await page.addInitScript(({ token }) => {
    window.localStorage.setItem('tg-signer-token', token)
    window.localStorage.setItem('theme', 'dark')
    window.localStorage.setItem('tg-signer-lang', 'zh-CN')
    document.documentElement.classList.add('dark')
  }, { token: MOCK_JWT })

  await setupApiMocks(page)

  console.log('Capturing screenshots...')

  // 1. Dashboard
  console.log('1. Navigating to Dashboard...')
  await page.goto('http://127.0.0.1:5199/dashboard')
  await page.waitForSelector('.ui-stat-card, h1, h2', { timeout: 10000 })
  await page.waitForTimeout(1500)
  await page.screenshot({ path: path.join(outputDir, '01-dashboard.png'), fullPage: false })
  console.log('✓ Saved 01-dashboard.png')

  // 2. Tasks
  console.log('2. Navigating to Tasks...')
  await page.goto('http://127.0.0.1:5199/tasks')
  await page.waitForSelector('.ui-card, button', { timeout: 10000 })
  await page.waitForTimeout(1500)
  await page.screenshot({ path: path.join(outputDir, '02-tasks.png'), fullPage: false })
  console.log('✓ Saved 02-tasks.png')

  // 3. Task Edit Modal (Action Flow)
  console.log('3. Opening Task Edit Modal...')
  try {
    const editBtn = page.locator('button').filter({ hasText: '编辑' }).first()
    if (await editBtn.isVisible()) {
      await editBtn.click()
      await page.waitForSelector('input#task-form-name, .ui-modal-container', { timeout: 5000 })
      await page.waitForTimeout(1000)
      await page.screenshot({ path: path.join(outputDir, '03-task-editor.png'), fullPage: false })
      console.log('✓ Saved 03-task-editor.png')
      const cancelBtn = page.locator('button').filter({ hasText: '取消' }).first()
      if (await cancelBtn.isVisible()) await cancelBtn.click()
      await page.waitForTimeout(500)
    }
  } catch (err) {
    console.warn('Task Edit modal capture skipped:', err.message)
  }

  // 4. Accounts
  console.log('4. Navigating to Accounts...')
  await page.goto('http://127.0.0.1:5199/accounts')
  await page.waitForSelector('.ui-card, button', { timeout: 10000 })
  await page.waitForTimeout(1500)
  await page.screenshot({ path: path.join(outputDir, '04-accounts.png'), fullPage: false })
  console.log('✓ Saved 04-accounts.png')

  // 5. Account QR / Login Modal
  console.log('5. Opening Add Account Modal...')
  try {
    const fabBtn = page.locator('button.ui-fab')
    if (await fabBtn.isVisible()) {
      await fabBtn.click()
      await page.waitForTimeout(400)
      const qrBtn = page.locator('button').filter({ hasText: '扫码登录' }).first()
      if (await qrBtn.isVisible()) {
        await qrBtn.click()
        await page.waitForTimeout(800)
        await page.screenshot({ path: path.join(outputDir, '05-account-modal.png'), fullPage: false })
        console.log('✓ Saved 05-account-modal.png')
        const closeBtn = page.locator('button').filter({ hasText: '取消' }).first()
        if (await closeBtn.isVisible()) await closeBtn.click()
        await page.waitForTimeout(500)
      }
    }
  } catch (err) {
    console.warn('Account modal capture skipped:', err.message)
  }

  // 6. Logs & Observability
  console.log('6. Navigating to Logs...')
  await page.goto('http://127.0.0.1:5199/logs')
  await page.waitForSelector('.ui-card, table, .ui-empty', { timeout: 10000 })
  await page.waitForTimeout(1500)
  await page.screenshot({ path: path.join(outputDir, '06-logs.png'), fullPage: false })
  console.log('✓ Saved 06-logs.png')

  // 7. Settings & WebDAV
  console.log('7. Navigating to Settings...')
  await page.goto('http://127.0.0.1:5199/settings')
  await page.waitForSelector('.ui-card, h2, h3', { timeout: 10000 })
  await page.waitForTimeout(1500)
  await page.screenshot({ path: path.join(outputDir, '07-settings.png'), fullPage: false })
  console.log('✓ Saved 07-settings.png')

  // 8. Mobile responsive view
  console.log('8. Capturing Mobile Responsive view...')
  const mobileContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
    colorScheme: 'dark',
    locale: 'zh-CN'
  })
  const mobilePage = await mobileContext.newPage()
  await mobilePage.addInitScript(({ token }) => {
    window.localStorage.setItem('tg-signer-token', token)
    window.localStorage.setItem('theme', 'dark')
    window.localStorage.setItem('tg-signer-lang', 'zh-CN')
    document.documentElement.classList.add('dark')
  }, { token: MOCK_JWT })

  await setupApiMocks(mobilePage)

  await mobilePage.goto('http://127.0.0.1:5199/dashboard')
  await mobilePage.waitForSelector('.ui-stat-card, h1, h2', { timeout: 10000 })
  await mobilePage.waitForTimeout(1500)
  await mobilePage.screenshot({ path: path.join(outputDir, '08-mobile.png'), fullPage: false })
  console.log('✓ Saved 08-mobile.png')

  // Generate aliases
  const aliases = [
    ['01-dashboard.png', 'dashboard.png'],
    ['02-tasks.png', 'tasks.png'],
    ['03-task-editor.png', 'task-editor.png'],
    ['04-accounts.png', 'accounts.png'],
    ['05-account-modal.png', 'account-modal.png'],
    ['06-logs.png', 'logs.png'],
    ['07-settings.png', 'settings.png'],
    ['08-mobile.png', 'mobile.png'],
  ]
  for (const [src, dst] of aliases) {
    const srcPath = path.join(outputDir, src)
    if (fs.existsSync(srcPath)) {
      fs.copyFileSync(srcPath, path.join(outputDir, dst))
    }
  }

  await browser.close()
  await server.close()
  console.log('All screenshots and aliases generated successfully!')
}

main().catch((err) => {
  console.error('Screenshot generation failed:', err)
  process.exit(1)
})

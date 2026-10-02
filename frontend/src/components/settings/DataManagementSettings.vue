<script setup lang="ts">
/**
 * 数据管理区块：配置 JSON 导入/导出、WebDAV 远端备份、自动备份策略、直接下载完整归档及灾难恢复指引。
 * 父组件 Settings.vue 持有表单状态并实现 API 调用；本组件仅负责 UI 与事件转发。
 */
import { ref, computed } from 'vue'
import {
  Database,
  Cloud,
  Clock,
  FileJson,
  HelpCircle,
  Copy,
  Check,
  HardDrive,
  RefreshCw,
  FolderGit2,
  AlertTriangle,
  Download,
  Archive,
  Sparkles,
} from 'lucide-vue-next'
import { useI18n } from '../../composables/useI18n'
import { parseNumberInputValue, type SettingsFormState } from '../../lib/settings-form'
import type { BackupStatus, RemoteBackupFile } from '../../lib/api'

const props = defineProps<{
  /** 全局表单状态（v-model） */
  modelValue: SettingsFormState
  /** 服务端是否已保存 WebDAV 密码 */
  webdavPasswordSet?: boolean
  /** 备份状态 */
  backupStatus: BackupStatus | null
  /** 远端 WebDAV 文件列表 */
  remoteFiles: RemoteBackupFile[]
  /** 远端列表提示消息 */
  remoteMessage: string
  /** 当前下载的远端文件名 */
  remoteDownloadName: string
  /** 数据加载中（导入/导出 JSON） */
  dataLoading?: boolean
  /** 完整备份导出中 */
  backupLoading?: boolean
  /** WebDAV 测试中 */
  webdavTestLoading?: boolean
  /** WebDAV 列表中 */
  webdavListLoading?: boolean
  /** 高级设置保存中（影响多个按钮禁用态） */
  advancedLoading?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: SettingsFormState): void
  (e: 'export-json'): void
  (e: 'import-json', file: File): void
  (e: 'backup-export'): void
  (e: 'backup-download'): void
  (e: 'webdav-test'): void
  (e: 'webdav-list'): void
  (e: 'webdav-download', name: string): void
  (e: 'save-advanced'): void
}>()

const { t } = useI18n()

// 顶级 Tab 控制
const activeTab = ref<'remote' | 'auto' | 'migrate'>('remote')

// 恢复指引弹窗
const showRestoreModal = ref(false)
const restoreEnvTab = ref<'docker' | 'host'>('docker')
const copied = ref(false)

const update = <K extends keyof SettingsFormState>(key: K, value: SettingsFormState[K]) => {
  emit('update:modelValue', { ...props.modelValue, [key]: value } as SettingsFormState)
}

const onStringInput = (key: keyof SettingsFormState, e: Event) => {
  update(key, (e.target as HTMLInputElement).value as never)
}

const onNumberInput = (key: keyof SettingsFormState, e: Event) => {
  const v = (e.target as HTMLInputElement).value
  update(key, parseNumberInputValue(v) as never)
}

/** 隐藏的文件输入：键盘/读屏用户通过下方按钮触发文件选择 */
const importFileRef = ref<HTMLInputElement | null>(null)

const onFileChange = (e: Event) => {
  const target = e.target as HTMLInputElement
  if (target.files && target.files[0]) {
    emit('import-json', target.files[0])
    target.value = ''
  }
}

const formatBytes = (n?: number | null) => {
  if (n == null || !Number.isFinite(n)) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let v = Number(n)
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return i === 0 ? `${Math.round(v)} ${units[i]}` : `${v.toFixed(1)} ${units[i]}`
}

// WebDAV 服务商快捷预设
interface WebdavPreset {
  id: string
  labelKey: string
  url: string
}

const webdavPresets: WebdavPreset[] = [
  {
    id: 'jianguoyun',
    labelKey: 'settings.presetJianguoyun',
    url: 'https://dav.jianguoyun.com/dav/',
  },
  {
    id: 'nextcloud',
    labelKey: 'settings.presetNextcloud',
    url: 'https://your-domain/remote.php/dav/files/USERNAME/',
  },
  {
    id: 'infinicloud',
    labelKey: 'settings.presetInfinicloud',
    url: 'https://teracloud.jp/dav/',
  },
  {
    id: 'alist',
    labelKey: 'settings.presetAlist',
    url: 'https://your-alist-domain/dav',
  },
]

const applyWebdavPreset = (preset: WebdavPreset) => {
  emit('update:modelValue', {
    ...props.modelValue,
    webdavUrl: preset.url,
    webdavRemoteDir: props.modelValue.webdavRemoteDir || 'tg-signpulse-backups',
  })
}



// 灾难恢复命令与脚本
const restoreCommand = computed(() => {
  const dataDir = props.backupStatus?.data_dir || '/app/data'
  if (restoreEnvTab.value === 'docker') {
    return `# 1. 停止运行中的容器\ndocker stop tg-signpulse\n\n# 2. 将备份包解压覆盖至宿主机挂载目录（请将 <宿主机数据挂载目录> 替换为实际宿主机路径，例如 ./data）\ntar -xzf tg-signpulse-backup-*.tar.gz -C "<宿主机数据挂载目录，如 ./data>"\n\n# 3. 重新启动容器\ndocker start tg-signpulse`
  }
  return `# 1. 停止后台服务进程\npkill -f "backend.main"\n\n# 2. 解压覆盖到数据目录\ntar -xzf tg-signpulse-backup-*.tar.gz -C "${dataDir}"\n\n# 3. 重新拉起后台服务\nnohup python3 -m backend.main > run.log 2>&1 &`
})

const copyRestoreCommand = async () => {
  try {
    await navigator.clipboard.writeText(restoreCommand.value)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch {
    // fallback
  }
}
</script>

<template>
  <section class="ui-card p-6">
    <!-- Header -->
    <div class="mb-5 border-b border-[var(--sp-border)] pb-3 flex items-start justify-between gap-3">
      <div class="flex items-start gap-3">
        <span class="ui-section-icon" aria-hidden="true"><Database class="w-3.5 h-3.5" /></span>
        <div>
          <h2 class="text-base font-medium text-[var(--sp-text)] font-semibold">{{ t('settings.dataManagement') }}</h2>
          <p class="text-[11px] text-[var(--sp-text-muted)] mt-0.5">{{ t('settings.dataManagementDesc') }}</p>
        </div>
      </div>
      <!-- 快速灾难恢复指引入口 -->
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-brand-600 dark:text-brand-400 bg-brand-50/60 dark:bg-brand-950/30 hover:bg-brand-100/70 dark:hover:bg-brand-900/40 rounded-[var(--sp-radius-lg)] transition-colors border border-brand-200/50 dark:border-brand-800/50 shrink-0"
        @click="showRestoreModal = true"
      >
        <HelpCircle class="w-3.5 h-3.5" />
        {{ t('settings.restoreGuide') }}
      </button>
    </div>

    <!-- Navigation Tabs -->
    <div class="flex border-b border-[var(--sp-border)] mb-5 gap-6 text-xs font-medium">
      <button
        type="button"
        class="pb-2.5 flex items-center gap-1.5 border-b-2 transition-colors"
        :class="activeTab === 'remote' ? 'border-brand-500 text-brand-600 dark:text-brand-400 font-semibold' : 'border-transparent text-[var(--sp-text-muted)] hover:text-[var(--sp-text-secondary)] dark:hover:text-[var(--sp-text-muted)]'"
        @click="activeTab = 'remote'"
      >
        <Cloud class="w-3.5 h-3.5" />
        {{ t('settings.tabRemoteBackup') }}
      </button>
      <button
        type="button"
        class="pb-2.5 flex items-center gap-1.5 border-b-2 transition-colors"
        :class="activeTab === 'auto' ? 'border-brand-500 text-brand-600 dark:text-brand-400 font-semibold' : 'border-transparent text-[var(--sp-text-muted)] hover:text-[var(--sp-text-secondary)] dark:hover:text-[var(--sp-text-muted)]'"
        @click="activeTab = 'auto'"
      >
        <Clock class="w-3.5 h-3.5" />
        {{ t('settings.tabAutoBackup') }}
      </button>
      <button
        type="button"
        class="pb-2.5 flex items-center gap-1.5 border-b-2 transition-colors"
        :class="activeTab === 'migrate' ? 'border-brand-500 text-brand-600 dark:text-brand-400 font-semibold' : 'border-transparent text-[var(--sp-text-muted)] hover:text-[var(--sp-text-secondary)] dark:hover:text-[var(--sp-text-muted)]'"
        @click="activeTab = 'migrate'"
      >
        <FileJson class="w-3.5 h-3.5" />
        {{ t('settings.tabConfigMigrate') }}
      </button>
    </div>

    <!-- TAB 1: WebDAV 远端备份 -->
    <div v-show="activeTab === 'remote'" class="space-y-5">
      <!-- 状态指示条 -->
      <div v-if="backupStatus" class="p-3 bg-[var(--sp-surface-subtle)] bg-[var(--sp-surface)]/[0.02] border border-[var(--sp-border)] dark:border-[var(--sp-border)] rounded-[var(--sp-radius-lg)] text-xs space-y-1.5">
        <div class="flex flex-wrap items-center justify-between gap-2 text-[var(--sp-text-secondary)] dark:text-[var(--sp-text-secondary)]">
          <span class="font-mono flex items-center gap-1.5 truncate">
            <HardDrive class="w-3.5 h-3.5 text-[var(--sp-text-muted)] shrink-0" />
            {{ backupStatus.data_dir }}
            <span class="text-[var(--sp-text-muted)]">· {{ backupStatus.size_human }}</span>
            <span :class="backupStatus.writable ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'">
              ({{ backupStatus.writable ? t('settings.backupWritable') : t('settings.backupReadonly') }})
            </span>
          </span>
          <div class="flex items-center gap-2 text-[11px]">
            <span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-[var(--sp-surface-muted)] dark:bg-[var(--sp-surface-muted)]">
              WebDAV:
              <span :class="backupStatus.webdav_configured ? 'text-emerald-600 dark:text-emerald-400 font-medium' : 'text-[var(--sp-text-muted)]'">
                {{ backupStatus.webdav_configured ? t('settings.webdavConfiguredYes') : t('settings.webdavConfiguredNo') }}
              </span>
            </span>
          </div>
        </div>
      </div>



      <!-- WebDAV 配置区块 -->
      <div class="space-y-4">
        <div>
          <h3 class="text-sm font-medium text-[var(--sp-text)] font-semibold">{{ t('settings.fullBackup') }}</h3>
          <p class="text-xs text-[var(--sp-text-muted)] mt-0.5 leading-relaxed">{{ t('settings.fullBackupDesc') }}</p>
        </div>

        <!-- WebDAV 快捷预设 (Quick Presets) -->
        <div class="p-2.5 rounded-[var(--sp-radius-lg)] bg-[var(--sp-surface-subtle)] bg-[var(--sp-surface)]/[0.02] border border-[var(--sp-border)] dark:border-[var(--sp-border)] space-y-1.5">
          <div class="flex items-center gap-1.5 text-xs text-[var(--sp-text-secondary)] dark:text-[var(--sp-text-secondary)] font-medium">
            <Sparkles class="w-3.5 h-3.5 text-amber-500" />
            <span>{{ t('settings.quickPresets') }}</span>
            <span class="text-[10px] text-[var(--sp-text-muted)] font-normal">({{ t('settings.quickPresetsHint') }})</span>
          </div>
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="preset in webdavPresets"
              :key="preset.id"
              type="button"
              class="px-2.5 py-1 text-[11px] rounded-[var(--sp-radius)] font-medium transition-colors bg-[var(--sp-surface)] dark:bg-[var(--sp-surface-muted)] text-[var(--sp-text-secondary)] dark:text-[var(--sp-text)] hover:text-brand-600 dark:hover:text-brand-400 hover:border-brand-300 dark:hover:border-brand-700 border border-[var(--sp-border)] dark:border-[var(--sp-border)] shadow-xs"
              @click="applyWebdavPreset(preset)"
            >
              {{ t(preset.labelKey) }}
            </button>
          </div>
        </div>

        <div class="space-y-1.5">
          <label class="ui-label" for="webdav-url">{{ t('settings.webdavUrl') }}</label>
          <input
            id="webdav-url"
            :value="modelValue.webdavUrl"
            @input="onStringInput('webdavUrl', $event)"
            type="url"
            :placeholder="t('settings.webdavUrlPlaceholder')"
            class="ui-input"
            autocomplete="off"
          >
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <div class="space-y-1.5">
            <label class="ui-label" for="webdav-username">{{ t('settings.webdavUsername') }}</label>
            <input
              id="webdav-username"
              :value="modelValue.webdavUsername"
              @input="onStringInput('webdavUsername', $event)"
              type="text"
              class="ui-input"
              autocomplete="username"
            >
          </div>
          <div class="space-y-1.5">
            <label class="ui-label" for="webdav-password">{{ t('settings.webdavPassword') }}</label>
            <input
              id="webdav-password"
              :value="modelValue.webdavPassword"
              @input="onStringInput('webdavPassword', $event)"
              type="password"
              class="ui-input"
              autocomplete="current-password"
              :placeholder="webdavPasswordSet ? t('settings.webdavPasswordSavedHint') : t('settings.webdavPasswordHint')"
            >
          </div>
        </div>

        <div class="space-y-1.5">
          <label class="ui-label" for="webdav-remote-dir">{{ t('settings.webdavRemoteDir') }}</label>
          <input
            id="webdav-remote-dir"
            :value="modelValue.webdavRemoteDir"
            @input="onStringInput('webdavRemoteDir', $event)"
            type="text"
            placeholder="tg-signpulse-backups"
            class="ui-input"
          >
        </div>

        <div class="flex flex-col sm:flex-row gap-2 pt-1">
          <button
            type="button"
            class="ui-btn-secondary flex-1 !px-4 !py-2"
            :disabled="webdavTestLoading || advancedLoading"
            @click="emit('webdav-test')"
          >
            {{ webdavTestLoading ? t('settings.testing') : t('settings.webdavTest') }}
          </button>
          <button
            type="button"
            class="ui-btn-secondary flex-1 !px-4 !py-2 flex items-center justify-center gap-1.5"
            :disabled="webdavListLoading || advancedLoading"
            @click="emit('webdav-list')"
          >
            <RefreshCw v-if="webdavListLoading" class="w-3.5 h-3.5 animate-spin" />
            {{ webdavListLoading ? t('common.processing') : t('settings.webdavListRemote') }}
          </button>
        </div>

        <!-- WebDAV 远端文件列表 -->
        <div v-if="remoteFiles.length || remoteMessage" class="text-xs space-y-2 pt-2 border-t border-[var(--sp-border)] dark:border-[var(--sp-border)]">
          <div class="flex items-center justify-between text-[var(--sp-text-muted)]">
            <span v-if="remoteFiles.length" class="text-[11px] font-medium text-[var(--sp-text-secondary)] dark:text-[var(--sp-text-secondary)]">
              {{ t('settings.remoteFilesCount', { count: remoteFiles.length }) }}
            </span>
            <span v-else-if="remoteMessage" class="text-[11px]">{{ remoteMessage }}</span>
            <span class="text-[10px] text-[var(--sp-text-muted)]">{{ t('settings.webdavDownloadHint') }}</span>
          </div>

          <ul v-if="remoteFiles.length" class="space-y-1.5 max-h-44 overflow-y-auto">
            <li
              v-for="f in remoteFiles"
              :key="f.name + (f.mtime || '')"
              class="flex items-center justify-between gap-2 p-2 rounded-[var(--sp-radius-lg)] bg-[var(--sp-surface-subtle)] bg-[var(--sp-surface)]/[0.02] border border-[var(--sp-border)] dark:border-[var(--sp-border)] hover:bg-[var(--sp-surface-muted)] dark:bg-[var(--sp-surface-muted)] transition-colors"
            >
              <div class="flex items-center gap-2 min-w-0">
                <Archive class="w-3.5 h-3.5 text-brand-500 shrink-0" />
                <span class="font-mono text-xs text-[var(--sp-text-secondary)] dark:text-[var(--sp-text)] truncate">{{ f.name }}</span>
                <span v-if="f.size_bytes != null" class="text-[10px] px-1.5 py-0.2 rounded bg-[var(--sp-surface-muted)] dark:bg-[var(--sp-surface-muted)] text-[var(--sp-text-secondary)] dark:text-[var(--sp-text-secondary)] shrink-0">
                  {{ formatBytes(f.size_bytes) }}
                </span>
                <span v-if="f.mtime" class="text-[10px] text-[var(--sp-text-muted)] hidden sm:inline shrink-0">· {{ f.mtime }}</span>
              </div>
              <button
                type="button"
                class="ui-btn-secondary shrink-0 !px-2.5 !py-1 !text-xs flex items-center gap-1"
                :disabled="remoteDownloadName === f.name"
                @click="emit('webdav-download', f.name)"
              >
                <RefreshCw v-if="remoteDownloadName === f.name" class="w-3 h-3 animate-spin" />
                <Download v-else class="w-3 h-3" />
                {{ remoteDownloadName === f.name ? t('common.processing') : t('settings.webdavDownload') }}
              </button>
            </li>
          </ul>
        </div>
      </div>

      <!-- 立即创建备份主按钮 -->
      <div class="pt-4 border-t border-[var(--sp-border)] space-y-1.5">
        <button
          type="button"
          class="ui-btn-primary w-full !px-4 !py-2.5 flex items-center justify-center gap-2"
          :disabled="backupLoading"
          @click="emit('backup-export')"
        >
          <RefreshCw v-if="backupLoading" class="w-4 h-4 animate-spin" />
          <Cloud v-else class="w-4 h-4" />
          {{ backupLoading ? t('common.processing') : t('settings.exportBackupAction') }}
        </button>
      </div>
    </div>

    <!-- TAB 2: 定时与生命周期 -->
    <div v-show="activeTab === 'auto'" class="space-y-4">
      <div class="p-4 bg-[var(--sp-surface-subtle)] bg-[var(--sp-surface)]/[0.015] border border-[var(--sp-border)] dark:border-[var(--sp-border)] rounded-[var(--sp-radius-lg)] space-y-4">
        <div class="flex items-center justify-between gap-3">
          <div>
            <label class="text-xs font-medium text-[var(--sp-text-secondary)] dark:text-[var(--sp-text)] block">{{ t('settings.autoBackup') }}</label>
            <p class="text-[11px] text-[var(--sp-text-muted)] mt-0.5 leading-relaxed">{{ t('settings.autoBackupDesc') }}</p>
          </div>
          <button
            type="button"
            class="ui-switch"
            role="switch"
            :aria-label="t('settings.autoBackup')"
            :aria-checked="modelValue.autoBackupEnabled"
            :class="modelValue.autoBackupEnabled ? 'ui-switch-on' : ''"
            @click="update('autoBackupEnabled', !modelValue.autoBackupEnabled)"
          >
            <span class="ui-switch-knob" />
          </button>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
          <div class="space-y-1">
            <label class="text-xs text-[var(--sp-text-secondary)] dark:text-[var(--sp-text-secondary)]">{{ t('settings.autoBackupInterval') }}</label>
            <input
              :value="modelValue.autoBackupInterval"
              @input="onNumberInput('autoBackupInterval', $event)"
              type="number"
              min="1"
              max="168"
              class="ui-input"
              :disabled="!modelValue.autoBackupEnabled"
            />
            <p class="text-[10px] text-[var(--sp-text-muted)]">{{ t('settings.autoBackupIntervalHint') }}</p>
          </div>
          <div class="space-y-1">
            <label class="text-xs text-[var(--sp-text-secondary)] dark:text-[var(--sp-text-secondary)]">{{ t('settings.autoBackupKeep') }}</label>
            <input
              :value="modelValue.autoBackupKeep"
              @input="onNumberInput('autoBackupKeep', $event)"
              type="number"
              min="1"
              max="30"
              class="ui-input"
              :disabled="!modelValue.autoBackupEnabled"
            />
            <p class="text-[10px] text-[var(--sp-text-muted)]">{{ t('settings.autoBackupKeepHint') }}</p>
          </div>
        </div>

        <button
          type="button"
          class="ui-btn-secondary w-full !py-2 !text-xs mt-2"
          :disabled="advancedLoading"
          @click="emit('save-advanced')"
        >
          {{ advancedLoading ? t('common.saving') : t('settings.saveBackupSettings') }}
        </button>
      </div>

      <!-- 本地自动备份记录展示 -->
      <div v-if="backupStatus?.local_auto_backups?.length" class="space-y-2 pt-2">
        <h4 class="text-xs font-medium text-[var(--sp-text-secondary)] dark:text-[var(--sp-text-secondary)]">{{ t('settings.localAutoBackups') }}</h4>
        <div class="space-y-1.5 max-h-40 overflow-y-auto">
          <div
            v-for="b in backupStatus.local_auto_backups"
            :key="b.name"
            class="flex items-center justify-between p-2 rounded bg-[var(--sp-surface-subtle)] bg-[var(--sp-surface)]/[0.02] border border-[var(--sp-border)] dark:border-[var(--sp-border)] text-xs font-mono"
          >
            <span class="truncate">{{ b.name }}</span>
            <span class="text-[var(--sp-text-muted)] text-[11px] shrink-0">{{ b.size_human }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 3: 完整数据备份与配置迁移 -->
    <div v-show="activeTab === 'migrate'" class="space-y-5">
      <!-- 完整数据归档直接下载 -->
      <div class="p-4 bg-[var(--sp-surface-subtle)] bg-[var(--sp-surface)]/[0.015] border border-[var(--sp-border)] dark:border-[var(--sp-border)] rounded-[var(--sp-radius-lg)] space-y-3">
        <div>
          <h3 class="text-sm font-medium text-[var(--sp-text)] font-semibold flex items-center gap-1.5">
            <Archive class="w-4 h-4 text-brand-500" />
            {{ t('settings.fullArchiveDownloadTitle') }}
          </h3>
          <p class="text-xs text-[var(--sp-text-muted)] mt-1 leading-relaxed">{{ t('settings.fullArchiveDownloadDesc') }}</p>
        </div>
        <button
          type="button"
          class="ui-btn-primary w-full !px-4 !py-2.5 flex items-center justify-center gap-2"
          :disabled="backupLoading"
          @click="emit('backup-download')"
        >
          <RefreshCw v-if="backupLoading" class="w-4 h-4 animate-spin" />
          <Download v-else class="w-4 h-4" />
          {{ backupLoading ? t('common.processing') : t('settings.fullArchiveDownloadAction') }}
        </button>
      </div>

      <!-- 轻量配置 JSON 迁移 -->
      <div class="p-4 bg-[var(--sp-surface-subtle)] bg-[var(--sp-surface)]/[0.015] border border-[var(--sp-border)] dark:border-[var(--sp-border)] rounded-[var(--sp-radius-lg)] space-y-3">
        <div>
          <h3 class="text-sm font-medium text-[var(--sp-text)] font-semibold flex items-center gap-1.5">
            <FileJson class="w-4 h-4 text-amber-500" />
            {{ t('settings.configMigrateTitle') }}
          </h3>
          <p class="text-xs text-[var(--sp-text-muted)] mt-1 leading-relaxed">{{ t('settings.configMigrateDesc') }}</p>
        </div>

        <div class="flex flex-col sm:flex-row gap-3 pt-1">
          <button
            type="button"
            class="ui-btn-secondary flex-1 !px-4 !py-2 flex items-center justify-center gap-1.5"
            :disabled="dataLoading"
            @click="emit('export-json')"
          >
            <Download class="w-4 h-4" />
            {{ dataLoading ? t('common.processing') : t('settings.exportJson') }}
          </button>
          <div class="relative flex-1">
            <input
              ref="importFileRef"
              type="file"
              accept="application/json,.json"
              class="hidden"
              :disabled="dataLoading"
              @change="onFileChange"
            />
            <button
              type="button"
              class="ui-btn-secondary w-full !px-4 !py-2 flex items-center justify-center gap-1.5"
              :disabled="dataLoading"
              @click="importFileRef?.click()"
            >
              <FolderGit2 class="w-4 h-4" />
              {{ t('settings.importJson') }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 灾难恢复指引模态框 -->
    <Teleport to="body">
      <div
        v-if="showRestoreModal"
        class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-fade-in"
        @click.self="showRestoreModal = false"
      >
        <div class="bg-[var(--sp-surface)] dark:bg-[var(--sp-surface-elevated)] rounded-[var(--sp-radius-card)] shadow-xl max-w-xl w-full border border-[var(--sp-border)] dark:border-[var(--sp-border)] p-5 space-y-4">
          <div class="flex items-center justify-between pb-3 border-b border-[var(--sp-border)] dark:border-[var(--sp-border)]">
            <div class="flex items-center gap-2">
              <AlertTriangle class="w-4 h-4 text-amber-500" />
              <h3 class="text-sm font-semibold text-[var(--sp-text)] font-semibold">{{ t('settings.restoreGuideTitle') }}</h3>
            </div>
            <button
              type="button"
              class="text-[var(--sp-text-muted)] hover:text-[var(--sp-text-secondary)] dark:hover:text-[var(--sp-text)] text-lg leading-none"
              @click="showRestoreModal = false"
            >
              ×
            </button>
          </div>

          <p class="text-xs text-[var(--sp-text-secondary)] dark:text-[var(--sp-text-secondary)] leading-relaxed">
            {{ t('settings.restoreGuideSubtitle') }}
          </p>

          <!-- 停服警告提示 -->
          <div class="p-2.5 rounded bg-amber-500/10 border border-amber-500/20 text-xs text-amber-700 dark:text-amber-400 flex items-start gap-2">
            <AlertTriangle class="w-4 h-4 shrink-0 mt-0.5" />
            <div class="space-y-1">
              <p class="font-medium">{{ t('settings.restoreGuideStep1') }}</p>
              <p class="text-[11px] opacity-90">{{ t('settings.restoreGuideStep2') }}</p>
            </div>
          </div>

          <!-- 恢复环境切换 -->
          <div class="flex border-b border-[var(--sp-border)] dark:border-[var(--sp-border)] gap-4 text-xs">
            <button
              type="button"
              class="pb-1.5 font-medium transition-colors border-b-2"
              :class="restoreEnvTab === 'docker' ? 'border-brand-500 text-brand-600 dark:text-brand-400' : 'border-transparent text-[var(--sp-text-muted)] hover:text-[var(--sp-text-secondary)] dark:hover:text-[var(--sp-text-muted)]'"
              @click="restoreEnvTab = 'docker'"
            >
              {{ t('settings.restoreGuideTabDocker') }}
            </button>
            <button
              type="button"
              class="pb-1.5 font-medium transition-colors border-b-2"
              :class="restoreEnvTab === 'host' ? 'border-brand-500 text-brand-600 dark:text-brand-400' : 'border-transparent text-[var(--sp-text-muted)] hover:text-[var(--sp-text-secondary)] dark:hover:text-[var(--sp-text-muted)]'"
              @click="restoreEnvTab = 'host'"
            >
              {{ t('settings.restoreGuideTabHost') }}
            </button>
          </div>

          <!-- 命令展示区 -->
          <div class="relative bg-[var(--sp-terminal-bg)] rounded-[var(--sp-radius-lg)] p-3 text-[var(--sp-text)] font-mono text-xs overflow-x-auto">
            <button
              type="button"
              class="absolute top-2.5 right-2.5 p-1 rounded bg-[var(--sp-surface-muted)] text-[var(--sp-text-muted)] hover:text-[var(--sp-text)] transition-colors"
              :title="t('common.copy')"
              @click="copyRestoreCommand"
            >
              <Check v-if="copied" class="w-3.5 h-3.5 text-emerald-400" />
              <Copy v-else class="w-3.5 h-3.5" />
            </button>
            <pre class="whitespace-pre-wrap leading-relaxed">{{ restoreCommand }}</pre>
          </div>

          <div class="flex justify-end pt-2">
            <button
              type="button"
              class="ui-btn-secondary !text-xs !px-4 !py-1.5"
              @click="showRestoreModal = false"
            >
              {{ t('common.close') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
/**
 * 数据管理区块：配置 JSON 导入/导出、WebDAV / 对象存储完整备份、自动备份开关、远端备份列表及灾难恢复指引。
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
  Layers,
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
  /** 服务端是否已保存对象存储 Secret Key */
  s3SecretKeySet?: boolean
  /** 远端对象存储文件列表 */
  remoteS3Files: RemoteBackupFile[]
  /** 对象存储远端列表提示消息 */
  remoteS3Message: string
  /** 当前下载的对象存储文件名 */
  remoteS3DownloadName: string
  /** 数据加载中（导入/导出 JSON） */
  dataLoading?: boolean
  /** 完整备份导出中 */
  backupLoading?: boolean
  /** WebDAV 测试中 */
  webdavTestLoading?: boolean
  /** WebDAV 列表中 */
  webdavListLoading?: boolean
  /** 对象存储测试中 */
  s3TestLoading?: boolean
  /** 对象存储列表中 */
  s3ListLoading?: boolean
  /** 高级设置保存中（影响多个按钮禁用态） */
  advancedLoading?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: SettingsFormState): void
  (e: 'export-json'): void
  (e: 'import-json', file: File): void
  (e: 'backup-export'): void
  (e: 'webdav-test'): void
  (e: 'webdav-list'): void
  (e: 'webdav-download', name: string): void
  (e: 's3-test'): void
  (e: 's3-list'): void
  (e: 's3-download', name: string): void
  (e: 'save-advanced'): void
}>()

const { t } = useI18n()

// 顶级 Tab 控制
const activeTab = ref<'remote' | 'auto' | 'migrate'>('remote')

// 远端存储分段控制（保留与原有 DOM 测试一致的顺序：WebDAV / S3）
const remoteStorageType = ref<'webdav' | 's3'>('webdav')

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

// S3 服务商快捷预设
interface S3Preset {
  id: string
  name: string
  endpoint: string
  region: string
}

const s3Presets: S3Preset[] = [
  {
    id: 'r2',
    name: 'Cloudflare R2',
    endpoint: 'https://your-account-id.r2.cloudflarestorage.com',
    region: 'auto',
  },
  {
    id: 'aws',
    name: 'AWS S3',
    endpoint: 'https://s3.us-east-1.amazonaws.com',
    region: 'us-east-1',
  },
  {
    id: 'minio',
    name: 'MinIO',
    endpoint: 'http://127.0.0.1:9000',
    region: 'us-east-1',
  },
  {
    id: 'oss',
    name: 'Aliyun OSS',
    endpoint: 'https://oss-cn-hangzhou.aliyuncs.com',
    region: 'oss-cn-hangzhou',
  },
]

const applyS3Preset = (preset: S3Preset) => {
  emit('update:modelValue', {
    ...props.modelValue,
    s3EndpointUrl: preset.endpoint,
    s3Region: preset.region,
    s3Enabled: true,
    s3Prefix: props.modelValue.s3Prefix || 'tg-signpulse-backups',
  })
}

// 动态计算立即备份按钮文案与说明
const backupActionButtonInfo = computed(() => {
  const target = props.modelValue.backupTarget || 'auto'
  if (target === 'both') {
    return {
      label: t('settings.exportBackupBothAction'),
      hint: t('settings.backupTargetBothHint'),
    }
  }
  if (target === 's3') {
    return {
      label: t('settings.exportBackupS3Action'),
      hint: t('settings.backupTargetS3Hint'),
    }
  }
  if (target === 'webdav') {
    return {
      label: t('settings.exportBackupWebdavAction'),
      hint: t('settings.backupTargetWebdavHint'),
    }
  }
  return {
    label: t('settings.exportBackupAction'),
    hint: t('settings.backupTargetAutoHint'),
  }
})

// 灾难恢复命令与脚本
const restoreCommand = computed(() => {
  const dataDir = props.backupStatus?.data_dir || '/app/data'
  if (restoreEnvTab.value === 'docker') {
    return `# 1. 停止运行中的容器\ndocker stop tg-signpulse\n\n# 2. 将备份包解压覆盖至宿主机挂载目录（请将 <宿主机数据挂载目录> 替换为实际宿主机路径，例如 ./data）\ntar -xzf tg-signpulse-backup-*.tar.gz -C "<宿主机挂载目录，如 ./data>"\n\n# 3. 重新启动容器\ndocker start tg-signpulse`
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
    <div class="mb-5 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-start justify-between gap-3">
      <div class="flex items-start gap-3">
        <span class="ui-section-icon" aria-hidden="true"><Database class="w-3.5 h-3.5" /></span>
        <div>
          <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.dataManagement') }}</h2>
          <p class="text-[11px] text-gray-500 mt-0.5">{{ t('settings.dataManagementDesc') }}</p>
        </div>
      </div>
      <!-- 快速灾难恢复指引入口 -->
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-brand-600 dark:text-brand-400 bg-brand-50/60 dark:bg-brand-950/30 hover:bg-brand-100/70 dark:hover:bg-brand-900/40 rounded-lg transition-colors border border-brand-200/50 dark:border-brand-800/50 shrink-0"
        @click="showRestoreModal = true"
      >
        <HelpCircle class="w-3.5 h-3.5" />
        {{ t('settings.restoreGuide') }}
      </button>
    </div>

    <!-- Navigation Tabs -->
    <div class="flex border-b border-gray-200 dark:border-gray-800 mb-5 gap-6 text-xs font-medium">
      <button
        type="button"
        class="pb-2.5 flex items-center gap-1.5 border-b-2 transition-colors"
        :class="activeTab === 'remote' ? 'border-brand-500 text-brand-600 dark:text-brand-400 font-semibold' : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'"
        @click="activeTab = 'remote'"
      >
        <Cloud class="w-3.5 h-3.5" />
        {{ t('settings.tabRemoteBackup') }}
      </button>
      <button
        type="button"
        class="pb-2.5 flex items-center gap-1.5 border-b-2 transition-colors"
        :class="activeTab === 'auto' ? 'border-brand-500 text-brand-600 dark:text-brand-400 font-semibold' : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'"
        @click="activeTab = 'auto'"
      >
        <Clock class="w-3.5 h-3.5" />
        {{ t('settings.tabAutoBackup') }}
      </button>
      <button
        type="button"
        class="pb-2.5 flex items-center gap-1.5 border-b-2 transition-colors"
        :class="activeTab === 'migrate' ? 'border-brand-500 text-brand-600 dark:text-brand-400 font-semibold' : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'"
        @click="activeTab = 'migrate'"
      >
        <FileJson class="w-3.5 h-3.5" />
        {{ t('settings.tabConfigMigrate') }}
      </button>
    </div>

    <!-- TAB 1: 远端灾备与存储 (v-show 保留 DOM) -->
    <div v-show="activeTab === 'remote'" class="space-y-5">
      <!-- 状态指示条 -->
      <div v-if="backupStatus" class="p-3 bg-gray-50/80 dark:bg-white/[0.02] border border-gray-200/80 dark:border-gray-800/80 rounded-lg text-xs space-y-1.5">
        <div class="flex flex-wrap items-center justify-between gap-2 text-gray-600 dark:text-gray-300">
          <span class="font-mono flex items-center gap-1.5 truncate">
            <HardDrive class="w-3.5 h-3.5 text-gray-400 shrink-0" />
            {{ backupStatus.data_dir }}
            <span class="text-gray-400">· {{ backupStatus.size_human }}</span>
            <span :class="backupStatus.writable ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'">
              ({{ backupStatus.writable ? t('settings.backupWritable') : t('settings.backupReadonly') }})
            </span>
          </span>
          <div class="flex items-center gap-2 text-[11px]">
            <span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800">
              WebDAV:
              <span :class="backupStatus.webdav_configured ? 'text-emerald-600 dark:text-emerald-400 font-medium' : 'text-gray-400'">
                {{ backupStatus.webdav_configured ? t('settings.webdavConfiguredYes') : t('settings.webdavConfiguredNo') }}
              </span>
            </span>
            <span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800">
              S3:
              <span :class="backupStatus.s3_configured ? 'text-emerald-600 dark:text-emerald-400 font-medium' : 'text-gray-400'">
                {{ backupStatus.s3_configured ? t('settings.webdavConfiguredYes') : t('settings.webdavConfiguredNo') }}
              </span>
            </span>
          </div>
        </div>
      </div>

      <!-- 落点策略配置 -->
      <div class="p-4 bg-gray-50/50 dark:bg-white/[0.015] border border-gray-200/60 dark:border-gray-800/60 rounded-lg space-y-2">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div>
            <label class="text-xs font-medium text-gray-800 dark:text-gray-200">{{ t('settings.backupTarget') }}</label>
            <p class="text-[11px] text-gray-500 mt-0.5">{{ t('settings.backupTargetDesc') }}</p>
          </div>
          <select
            id="backup-target"
            :value="modelValue.backupTarget || 'auto'"
            class="ui-input !w-auto text-xs py-1.5 px-3 min-w-[200px]"
            @change="onStringInput('backupTarget', $event)"
          >
            <option value="auto">{{ t('settings.backupTargetAuto') }}</option>
            <option value="both">{{ t('settings.backupTargetBoth') }}</option>
            <option value="s3">{{ t('settings.backupTargetS3') }}</option>
            <option value="webdav">{{ t('settings.backupTargetWebdav') }}</option>
          </select>
        </div>
        <p class="text-[11px] text-brand-600/90 dark:text-brand-400/90 flex items-center gap-1 pt-1">
          <Layers class="w-3.5 h-3.5 shrink-0" />
          {{ backupActionButtonInfo.hint }}
        </p>
      </div>

      <!-- 存储配置切换分段 (Segmented Controls) -->
      <div class="space-y-4">
        <div class="flex items-center justify-between border-b border-gray-200 dark:border-gray-800 pb-2">
          <div class="inline-flex p-0.5 bg-gray-100 dark:bg-gray-800/80 rounded-lg text-xs">
            <button
              type="button"
              class="px-3 py-1.5 rounded-md font-medium transition-all"
              :class="remoteStorageType === 'webdav' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 shadow-sm' : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'"
              @click="remoteStorageType = 'webdav'"
            >
              {{ t('settings.storageWebdav') }}
              <span v-if="modelValue.webdavUrl" class="ml-1 w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
            </button>
            <button
              type="button"
              class="px-3 py-1.5 rounded-md font-medium transition-all"
              :class="remoteStorageType === 's3' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 shadow-sm' : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'"
              @click="remoteStorageType = 's3'"
            >
              {{ t('settings.storageS3') }}
              <span v-if="modelValue.s3Enabled" class="ml-1 w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
            </button>
          </div>

          <div class="text-[11px] text-gray-500">
            <span v-if="remoteStorageType === 's3'">Cloudflare R2 / AWS S3 / MinIO</span>
            <span v-else>Nextcloud / 坚果云 / WebDAV Server</span>
          </div>
        </div>

        <!-- WebDAV 表单区块 (位于 DOM 前列，保持兼容) -->
        <div v-show="remoteStorageType === 'webdav'" class="space-y-3">
          <div>
            <h3 class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ t('settings.fullBackup') }}</h3>
            <p class="text-xs text-gray-500 mt-0.5 leading-relaxed">{{ t('settings.fullBackupDesc') }}</p>
          </div>
          <div class="space-y-1.5">
            <label class="ui-label" for="webdav-url">{{ t('settings.webdavUrl') }}</label>
            <input id="webdav-url" :value="modelValue.webdavUrl" @input="onStringInput('webdavUrl', $event)" type="url" :placeholder="t('settings.webdavUrlPlaceholder')" class="ui-input" autocomplete="off">
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <div class="space-y-1.5">
              <label class="ui-label" for="webdav-username">{{ t('settings.webdavUsername') }}</label>
              <input id="webdav-username" :value="modelValue.webdavUsername" @input="onStringInput('webdavUsername', $event)" type="text" class="ui-input" autocomplete="username">
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
            <input id="webdav-remote-dir" :value="modelValue.webdavRemoteDir" @input="onStringInput('webdavRemoteDir', $event)" type="text" placeholder="tg-signpulse-backups" class="ui-input">
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
          <div v-if="remoteFiles.length || remoteMessage" class="text-xs space-y-2 pt-2 border-t border-gray-100 dark:border-gray-800">
            <div class="flex items-center justify-between text-gray-500">
              <span v-if="remoteFiles.length" class="text-[11px] font-medium text-gray-700 dark:text-gray-300">
                {{ t('settings.remoteFilesCount', { count: remoteFiles.length }) }}
              </span>
              <span v-else-if="remoteMessage" class="text-[11px]">{{ remoteMessage }}</span>
              <span class="text-[10px] text-gray-400">{{ t('settings.webdavDownloadHint') }}</span>
            </div>

            <ul v-if="remoteFiles.length" class="space-y-1.5 max-h-44 overflow-y-auto">
              <li
                v-for="f in remoteFiles"
                :key="f.name + (f.mtime || '')"
                class="flex items-center justify-between gap-2 p-2 rounded-lg bg-gray-50/80 dark:bg-white/[0.02] border border-gray-200/60 dark:border-gray-800/60 hover:bg-gray-100/70 dark:hover:bg-gray-800/40 transition-colors"
              >
                <div class="flex items-center gap-2 min-w-0">
                  <Archive class="w-3.5 h-3.5 text-brand-500 shrink-0" />
                  <span class="font-mono text-xs text-gray-800 dark:text-gray-200 truncate">{{ f.name }}</span>
                  <span v-if="f.size_bytes != null" class="text-[10px] px-1.5 py-0.2 rounded bg-gray-200/60 dark:bg-gray-700/60 text-gray-600 dark:text-gray-300 shrink-0">
                    {{ formatBytes(f.size_bytes) }}
                  </span>
                  <span v-if="f.mtime" class="text-[10px] text-gray-400 hidden sm:inline shrink-0">· {{ f.mtime }}</span>
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

        <!-- S3 表单区块 (位于 DOM 后列，保持单测查找顺序不变) -->
        <div v-show="remoteStorageType === 's3'" class="space-y-3">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ t('settings.s3Title') }}</h3>
              <p class="text-xs text-gray-500 mt-0.5 leading-relaxed">{{ t('settings.s3Desc') }}</p>
            </div>
            <!-- 第一个 switch 严格兼容单测 wrapper.find('[role="switch"]') -->
            <div class="flex items-center gap-2">
              <span class="text-xs text-gray-600 dark:text-gray-400">{{ t('settings.s3Enabled') }}</span>
              <button
                type="button"
                class="ui-switch"
                role="switch"
                :aria-label="t('settings.s3Enabled')"
                :aria-checked="modelValue.s3Enabled"
                :class="modelValue.s3Enabled ? 'ui-switch-on' : ''"
                @click="update('s3Enabled', !modelValue.s3Enabled)"
              >
                <span class="ui-switch-knob" />
              </button>
            </div>
          </div>

          <!-- S3 服务商快捷预设 (Quick Presets) -->
          <div class="p-2.5 rounded-lg bg-gray-50/70 dark:bg-white/[0.02] border border-gray-200/50 dark:border-gray-800/50 space-y-1.5">
            <div class="flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-300 font-medium">
              <Sparkles class="w-3.5 h-3.5 text-amber-500" />
              <span>{{ t('settings.quickPresets') }}</span>
              <span class="text-[10px] text-gray-400 font-normal">({{ t('settings.quickPresetsHint') }})</span>
            </div>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="preset in s3Presets"
                :key="preset.id"
                type="button"
                class="px-2.5 py-1 text-[11px] rounded-md font-medium transition-colors bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 hover:text-brand-600 dark:hover:text-brand-400 hover:border-brand-300 dark:hover:border-brand-700 border border-gray-200/80 dark:border-gray-700/80 shadow-xs"
                @click="applyS3Preset(preset)"
              >
                {{ preset.name }}
              </button>
            </div>
          </div>

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <div class="space-y-1.5">
              <label class="ui-label" for="s3-endpoint-url">{{ t('settings.s3Endpoint') }}</label>
              <input id="s3-endpoint-url" :value="modelValue.s3EndpointUrl" @input="onStringInput('s3EndpointUrl', $event)" type="url" :placeholder="t('settings.s3EndpointPlaceholder')" class="ui-input" autocomplete="off">
            </div>
            <div class="space-y-1.5">
              <label class="ui-label" for="s3-bucket">{{ t('settings.s3Bucket') }}</label>
              <input id="s3-bucket" :value="modelValue.s3Bucket" @input="onStringInput('s3Bucket', $event)" type="text" class="ui-input" autocomplete="off">
            </div>
            <div class="space-y-1.5">
              <label class="ui-label" for="s3-access-key">{{ t('settings.s3AccessKey') }}</label>
              <input id="s3-access-key" :value="modelValue.s3AccessKey" @input="onStringInput('s3AccessKey', $event)" type="text" class="ui-input" autocomplete="off">
            </div>
            <div class="space-y-1.5">
              <label class="ui-label" for="s3-secret-key">{{ t('settings.s3SecretKey') }}</label>
              <input
                id="s3-secret-key"
                :value="modelValue.s3SecretKey"
                @input="onStringInput('s3SecretKey', $event)"
                type="password"
                class="ui-input"
                autocomplete="new-password"
                :placeholder="s3SecretKeySet ? t('settings.s3SecretKeySavedHint') : t('settings.s3SecretKeyHint')"
              >
            </div>
            <div class="space-y-1.5">
              <label class="ui-label" for="s3-region">{{ t('settings.s3Region') }}</label>
              <input id="s3-region" :value="modelValue.s3Region" @input="onStringInput('s3Region', $event)" type="text" placeholder="auto" class="ui-input">
            </div>
            <div class="space-y-1.5">
              <label class="ui-label" for="s3-prefix">{{ t('settings.s3Prefix') }}</label>
              <input id="s3-prefix" :value="modelValue.s3Prefix" @input="onStringInput('s3Prefix', $event)" type="text" placeholder="tg-signpulse-backups" class="ui-input">
            </div>
            <div class="space-y-1.5 sm:col-span-2">
              <label class="ui-label" for="s3-proxy">{{ t('settings.s3Proxy') }}</label>
              <input id="s3-proxy" :value="modelValue.s3Proxy" @input="onStringInput('s3Proxy', $event)" type="text" :placeholder="t('settings.s3ProxyPlaceholder')" class="ui-input">
            </div>
          </div>

          <div class="flex flex-col sm:flex-row gap-2 pt-1">
            <button
              type="button"
              class="ui-btn-secondary flex-1 !px-4 !py-2"
              :disabled="s3TestLoading || advancedLoading"
              @click="emit('s3-test')"
            >
              {{ s3TestLoading ? t('settings.testing') : t('settings.s3Test') }}
            </button>
            <button
              type="button"
              class="ui-btn-secondary flex-1 !px-4 !py-2 flex items-center justify-center gap-1.5"
              :disabled="s3ListLoading || advancedLoading"
              @click="emit('s3-list')"
            >
              <RefreshCw v-if="s3ListLoading" class="w-3.5 h-3.5 animate-spin" />
              {{ s3ListLoading ? t('common.processing') : t('settings.s3ListRemote') }}
            </button>
          </div>

          <!-- S3 远端文件列表 -->
          <div v-if="remoteS3Files.length || remoteS3Message" class="text-xs space-y-2 pt-2 border-t border-gray-100 dark:border-gray-800">
            <div class="flex items-center justify-between text-gray-500">
              <span v-if="remoteS3Files.length" class="text-[11px] font-medium text-gray-700 dark:text-gray-300">
                {{ t('settings.remoteFilesCount', { count: remoteS3Files.length }) }}
              </span>
              <span v-else-if="remoteS3Message" class="text-[11px]">{{ remoteS3Message }}</span>
              <span class="text-[10px] text-gray-400">{{ t('settings.s3DownloadHint') }}</span>
            </div>

            <ul v-if="remoteS3Files.length" class="space-y-1.5 max-h-44 overflow-y-auto">
              <li
                v-for="f in remoteS3Files"
                :key="f.name + (f.mtime || '')"
                class="flex items-center justify-between gap-2 p-2 rounded-lg bg-gray-50/80 dark:bg-white/[0.02] border border-gray-200/60 dark:border-gray-800/60 hover:bg-gray-100/70 dark:hover:bg-gray-800/40 transition-colors"
              >
                <div class="flex items-center gap-2 min-w-0">
                  <Archive class="w-3.5 h-3.5 text-brand-500 shrink-0" />
                  <span class="font-mono text-xs text-gray-800 dark:text-gray-200 truncate">{{ f.name }}</span>
                  <span v-if="f.size_bytes != null" class="text-[10px] px-1.5 py-0.2 rounded bg-gray-200/60 dark:bg-gray-700/60 text-gray-600 dark:text-gray-300 shrink-0">
                    {{ formatBytes(f.size_bytes) }}
                  </span>
                  <span v-if="f.mtime" class="text-[10px] text-gray-400 hidden sm:inline shrink-0">· {{ f.mtime }}</span>
                </div>
                <button
                  type="button"
                  class="ui-btn-secondary shrink-0 !px-2.5 !py-1 !text-xs flex items-center gap-1"
                  :disabled="remoteS3DownloadName === f.name"
                  @click="emit('s3-download', f.name)"
                >
                  <RefreshCw v-if="remoteS3DownloadName === f.name" class="w-3 h-3 animate-spin" />
                  <Download v-else class="w-3 h-3" />
                  {{ remoteS3DownloadName === f.name ? t('common.processing') : t('settings.s3Download') }}
                </button>
              </li>
            </ul>
          </div>
        </div>
      </div>

      <!-- 立即创建备份主按钮 -->
      <div class="pt-4 border-t border-gray-200 dark:border-gray-800/60 space-y-1.5">
        <button
          type="button"
          class="ui-btn-primary w-full !px-4 !py-2.5 flex items-center justify-center gap-2"
          :disabled="backupLoading"
          @click="emit('backup-export')"
        >
          <RefreshCw v-if="backupLoading" class="w-4 h-4 animate-spin" />
          <Cloud v-else class="w-4 h-4" />
          {{ backupLoading ? t('common.processing') : backupActionButtonInfo.label }}
        </button>
      </div>
    </div>

    <!-- TAB 2: 定时与生命周期 -->
    <div v-show="activeTab === 'auto'" class="space-y-4">
      <div class="p-4 bg-gray-50/50 dark:bg-white/[0.015] border border-gray-200/60 dark:border-gray-800/60 rounded-lg space-y-4">
        <div class="flex items-center justify-between gap-3">
          <div>
            <label class="text-xs font-medium text-gray-800 dark:text-gray-200 block">{{ t('settings.autoBackup') }}</label>
            <p class="text-[11px] text-gray-500 mt-0.5 leading-relaxed">{{ t('settings.autoBackupDesc') }}</p>
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
            <label class="text-xs text-gray-600 dark:text-gray-400">{{ t('settings.autoBackupInterval') }}</label>
            <input
              :value="modelValue.autoBackupInterval"
              @input="onNumberInput('autoBackupInterval', $event)"
              type="number"
              min="1"
              max="168"
              class="ui-input"
              :disabled="!modelValue.autoBackupEnabled"
            />
            <p class="text-[10px] text-gray-500">{{ t('settings.autoBackupIntervalHint') }}</p>
          </div>
          <div class="space-y-1">
            <label class="text-xs text-gray-600 dark:text-gray-400">{{ t('settings.autoBackupKeep') }}</label>
            <input
              :value="modelValue.autoBackupKeep"
              @input="onNumberInput('autoBackupKeep', $event)"
              type="number"
              min="1"
              max="30"
              class="ui-input"
              :disabled="!modelValue.autoBackupEnabled"
            />
            <p class="text-[10px] text-gray-500">{{ t('settings.autoBackupKeepHint') }}</p>
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
        <h4 class="text-xs font-medium text-gray-700 dark:text-gray-300">{{ t('settings.localAutoBackups') }}</h4>
        <div class="space-y-1.5 max-h-40 overflow-y-auto">
          <div
            v-for="b in backupStatus.local_auto_backups"
            :key="b.name"
            class="flex items-center justify-between p-2 rounded bg-gray-50 dark:bg-white/[0.02] border border-gray-200/50 dark:border-gray-800/50 text-xs font-mono"
          >
            <span class="truncate">{{ b.name }}</span>
            <span class="text-gray-400 text-[11px] shrink-0">{{ b.size_human }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 3: 配置迁移 JSON -->
    <div v-show="activeTab === 'migrate'" class="space-y-4">
      <div>
        <h3 class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ t('settings.configMigrateTitle') }}</h3>
        <p class="text-xs text-gray-500 mt-1 leading-relaxed">{{ t('settings.configMigrateDesc') }}</p>
      </div>

      <div class="flex flex-col sm:flex-row gap-3 pt-2">
        <button
          type="button"
          class="ui-btn-primary flex-1 !px-4 !py-2.5 flex items-center justify-center gap-1.5"
          :disabled="dataLoading"
          @click="emit('export-json')"
        >
          <FileJson class="w-4 h-4" />
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
            class="ui-btn-secondary w-full !px-4 !py-2.5 flex items-center justify-center gap-1.5"
            :disabled="dataLoading"
            @click="importFileRef?.click()"
          >
            <FolderGit2 class="w-4 h-4" />
            {{ t('settings.importJson') }}
          </button>
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
        <div class="bg-white dark:bg-gray-900 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-800 max-w-lg w-full p-6 space-y-4 text-left">
          <div class="flex items-start justify-between">
            <div class="flex items-center gap-2.5">
              <span class="p-2 rounded-lg bg-brand-50 dark:bg-brand-950/60 text-brand-600 dark:text-brand-400">
                <HelpCircle class="w-5 h-5" />
              </span>
              <div>
                <h3 class="text-base font-semibold text-gray-900 dark:text-gray-100">{{ t('settings.restoreGuideTitle') }}</h3>
                <p class="text-xs text-gray-500 mt-0.5">{{ t('settings.restoreGuideSubtitle') }}</p>
              </div>
            </div>
          </div>

          <!-- 环境选项卡切换 (Docker / 宿主机) -->
          <div class="flex gap-2 p-1 bg-gray-100 dark:bg-gray-800 rounded-lg text-xs font-medium">
            <button
              type="button"
              class="flex-1 py-1 px-3 rounded-md transition-all text-center"
              :class="restoreEnvTab === 'docker' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 shadow-xs font-semibold' : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'"
              @click="restoreEnvTab = 'docker'"
            >
              {{ t('settings.restoreGuideTabDocker') }}
            </button>
            <button
              type="button"
              class="flex-1 py-1 px-3 rounded-md transition-all text-center"
              :class="restoreEnvTab === 'host' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 shadow-xs font-semibold' : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'"
              @click="restoreEnvTab = 'host'"
            >
              {{ t('settings.restoreGuideTabHost') }}
            </button>
          </div>

          <div class="space-y-3 text-xs text-gray-600 dark:text-gray-300">
            <div class="p-3 bg-gray-50 dark:bg-gray-800/40 rounded-lg space-y-2 border border-gray-200/60 dark:border-gray-800/60">
              <p class="font-medium text-gray-900 dark:text-gray-100">{{ t('settings.restoreGuideStep1') }}</p>
              <p class="font-medium text-gray-900 dark:text-gray-100">{{ t('settings.restoreGuideStep2') }}</p>
              <div class="relative group mt-1.5">
                <pre class="bg-gray-950 text-gray-100 font-mono text-[11px] p-3 rounded-md overflow-x-auto select-all leading-relaxed whitespace-pre">{{ restoreCommand }}</pre>
                <button
                  type="button"
                  class="absolute top-2 right-2 p-1.5 rounded bg-gray-800 hover:bg-gray-700 text-gray-300 transition-colors shadow-sm"
                  :title="t('settings.restoreGuideCopyCmd')"
                  @click="copyRestoreCommand"
                >
                  <Check v-if="copied" class="w-3.5 h-3.5 text-emerald-400" />
                  <Copy v-else class="w-3.5 h-3.5" />
                </button>
              </div>
              <p class="font-medium text-gray-900 dark:text-gray-100 pt-1">{{ t('settings.restoreGuideStep3') }}</p>
            </div>

            <div class="flex items-start gap-2 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-amber-700 dark:text-amber-400">
              <AlertTriangle class="w-4 h-4 shrink-0 mt-0.5" />
              <p class="text-[11px] leading-relaxed">
                {{ t('settings.backupRestoreHint') }}
              </p>
            </div>
          </div>

          <div class="flex justify-end pt-2">
            <button
              type="button"
              class="ui-btn-primary !px-5 !py-2 text-xs"
              @click="showRestoreModal = false"
            >
              {{ t('settings.restoreGuideClose') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

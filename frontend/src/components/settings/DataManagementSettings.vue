<script setup lang="ts">
/**
 * 数据管理区块：配置 JSON 导入/导出、WebDAV / 对象存储完整备份、自动备份开关、远程备份列表。
 * 父组件 Settings.vue 持有表单状态并实现 API 调用；本组件仅负责 UI 与事件转发。
 */
import { ref } from 'vue'
import { Database } from 'lucide-vue-next'
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
  /** 远程 WebDAV 文件列表 */
  remoteFiles: RemoteBackupFile[]
  /** 远程列表提示消息 */
  remoteMessage: string
  /** 当前下载的远程文件名 */
  remoteDownloadName: string
  /** 服务端是否已保存对象存储 Secret Key */
  s3SecretKeySet?: boolean
  /** 远程对象存储文件列表 */
  remoteS3Files: RemoteBackupFile[]
  /** 对象存储远程列表提示消息 */
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
    // 清空 input，允许再次选择同一文件
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
</script>

<template>
  <section class="ui-card p-6">
    <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-start gap-3">
      <span class="ui-section-icon" aria-hidden="true"><Database class="w-3.5 h-3.5" /></span>
      <div>
        <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.dataManagement') }}</h2>
        <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.dataManagementDesc') }}</p>
      </div>
    </div>

    <!-- 配置迁移 JSON -->
    <div class="space-y-3 mb-6">
      <div>
        <h3 class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ t('settings.configMigrateTitle') }}</h3>
        <p class="text-xs text-gray-500 mt-1 leading-relaxed">{{ t('settings.configMigrateDesc') }}</p>
      </div>
      <div class="flex flex-col sm:flex-row gap-3">
        <button
          type="button"
          class="ui-btn-primary flex-1 !px-4 !py-2"
          :disabled="dataLoading"
          @click="emit('export-json')"
        >
          {{ dataLoading ? t('common.processing') : t('settings.exportJson') }}
        </button>
        <div class="relative flex-1">
          <!-- 透明覆盖层改按钮触发：覆盖层下的 input 无焦点环，
               键盘 Tab 会停在不可见控件上；改为按钮代理点击 -->
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
            class="ui-btn-secondary w-full !px-4 !py-2"
            :disabled="dataLoading"
            @click="importFileRef?.click()"
          >
            {{ t('settings.importJson') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 完整备份 → WebDAV -->
    <div class="pt-5 border-t border-gray-200 dark:border-gray-800/60 space-y-3">
      <div>
        <h3 class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ t('settings.fullBackup') }}</h3>
        <p class="text-xs text-gray-500 mt-1 leading-relaxed">{{ t('settings.fullBackupDesc') }}</p>
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
      <div class="flex flex-col sm:flex-row gap-2">
        <button
          type="button"
          class="ui-btn-primary flex-1 !px-4 !py-2"
          :disabled="backupLoading"
          @click="emit('backup-export')"
        >
          {{ backupLoading ? t('common.processing') : t('settings.exportBackupWebdav') }}
        </button>
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
          class="ui-btn-secondary flex-1 !px-4 !py-2"
          :disabled="webdavListLoading || advancedLoading"
          @click="emit('webdav-list')"
        >
          {{ webdavListLoading ? t('common.processing') : t('settings.webdavListRemote') }}
        </button>
      </div>
      <div v-if="remoteFiles.length || remoteMessage" class="text-xs space-y-1.5">
        <p v-if="remoteMessage" class="text-gray-500">{{ remoteMessage }}</p>
        <p class="text-[10px] text-gray-500">{{ t('settings.webdavDownloadHint') }}</p>
        <ul v-if="remoteFiles.length" class="text-[11px] text-gray-600 dark:text-gray-400 space-y-1 max-h-36 overflow-y-auto">
          <li
            v-for="f in remoteFiles"
            :key="f.name + (f.mtime || '')"
            class="flex items-center justify-between gap-2 font-mono"
          >
            <span class="min-w-0 truncate">
              {{ f.name }}
              <span v-if="f.size_bytes != null" class="text-gray-400">· {{ formatBytes(f.size_bytes) }}</span>
              <span v-if="f.mtime" class="text-gray-400">· {{ f.mtime }}</span>
            </span>
            <button
              type="button"
              class="ui-btn-secondary shrink-0 !px-2 !py-0.5 !text-[10px]"
              :disabled="remoteDownloadName === f.name"
              @click="emit('webdav-download', f.name)"
            >
              {{ remoteDownloadName === f.name ? t('common.processing') : t('settings.webdavDownload') }}
            </button>
          </li>
        </ul>
      </div>

      <!-- 备份到对象存储（S3 / Cloudflare R2 / MinIO），未配置 WebDAV 时生效 -->
      <div class="pt-5 border-t border-gray-200 dark:border-gray-800/60 space-y-3">
        <div>
          <h3 class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ t('settings.s3Title') }}</h3>
          <p class="text-xs text-gray-500 mt-1 leading-relaxed">{{ t('settings.s3Desc') }}</p>
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
          <div class="space-y-1.5">
            <label class="ui-label" for="s3-proxy">{{ t('settings.s3Proxy') }}</label>
            <input id="s3-proxy" :value="modelValue.s3Proxy" @input="onStringInput('s3Proxy', $event)" type="text" :placeholder="t('settings.s3ProxyPlaceholder')" class="ui-input">
          </div>
          <div class="space-y-1.5">
            <label class="ui-label">{{ t('settings.s3Enabled') }}</label>
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
            <p class="text-[10px] text-gray-500">{{ t('settings.s3EnabledHint') }}</p>
          </div>
        </div>
        <div class="flex flex-col sm:flex-row gap-2">
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
            class="ui-btn-secondary flex-1 !px-4 !py-2"
            :disabled="s3ListLoading || advancedLoading"
            @click="emit('s3-list')"
          >
            {{ s3ListLoading ? t('common.processing') : t('settings.s3ListRemote') }}
          </button>
        </div>
        <p class="text-[10px] text-gray-500">{{ t('settings.s3PriorityHint') }}</p>
        <div v-if="remoteS3Files.length || remoteS3Message" class="text-xs space-y-1.5">
          <p v-if="remoteS3Message" class="text-gray-500">{{ remoteS3Message }}</p>
          <p class="text-[10px] text-gray-500">{{ t('settings.s3DownloadHint') }}</p>
          <ul v-if="remoteS3Files.length" class="text-[11px] text-gray-600 dark:text-gray-400 space-y-1 max-h-36 overflow-y-auto">
            <li
              v-for="f in remoteS3Files"
              :key="f.name + (f.mtime || '')"
              class="flex items-center justify-between gap-2 font-mono"
            >
              <span class="min-w-0 truncate">
                {{ f.name }}
                <span v-if="f.size_bytes != null" class="text-gray-400">· {{ formatBytes(f.size_bytes) }}</span>
                <span v-if="f.mtime" class="text-gray-400">· {{ f.mtime }}</span>
              </span>
              <button
                type="button"
                class="ui-btn-secondary shrink-0 !px-2 !py-0.5 !text-[10px]"
                :disabled="remoteS3DownloadName === f.name"
                @click="emit('s3-download', f.name)"
              >
                {{ remoteS3DownloadName === f.name ? t('common.processing') : t('settings.s3Download') }}
              </button>
            </li>
          </ul>
        </div>
      </div>
      <div class="p-3 bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-gray-800/60 space-y-3">
        <div class="flex items-center justify-between gap-3">
          <div>
            <label class="text-xs text-gray-600 dark:text-gray-300 block">{{ t('settings.autoBackup') }}</label>
            <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.autoBackupDesc') }}</p>
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
        <div class="grid grid-cols-2 gap-2">
          <div class="space-y-1">
            <label class="text-[10px] text-gray-500">{{ t('settings.autoBackupInterval') }}</label>
            <input :value="modelValue.autoBackupInterval" @input="onNumberInput('autoBackupInterval', $event)" type="number" min="1" max="168" class="ui-input" :disabled="!modelValue.autoBackupEnabled" />
            <p class="text-[10px] text-gray-500">{{ t('settings.autoBackupIntervalHint') }}</p>
          </div>
          <div class="space-y-1">
            <label class="text-[10px] text-gray-500">{{ t('settings.autoBackupKeep') }}</label>
            <input :value="modelValue.autoBackupKeep" @input="onNumberInput('autoBackupKeep', $event)" type="number" min="1" max="30" class="ui-input" :disabled="!modelValue.autoBackupEnabled" />
            <p class="text-[10px] text-gray-500">{{ t('settings.autoBackupKeepHint') }}</p>
          </div>
        </div>
        <button type="button" class="ui-btn-secondary w-full !py-2 !text-xs" :disabled="advancedLoading" @click="emit('save-advanced')">
          {{ advancedLoading ? t('common.saving') : t('settings.saveBackupSettings') }}
        </button>
      </div>
      <div v-if="backupStatus" class="text-xs text-gray-500 space-y-1">
        <p class="font-mono">
          {{ backupStatus.data_dir }} · {{ backupStatus.size_human }}
          · {{ backupStatus.writable ? t('settings.backupWritable') : t('settings.backupReadonly') }}
        </p>
        <p>
          WebDAV:
          {{ backupStatus.webdav_configured ? t('settings.webdavConfiguredYes') : t('settings.webdavConfiguredNo') }}
          · {{ t('settings.s3Configured') }}:
          {{ backupStatus.s3_configured ? t('settings.webdavConfiguredYes') : t('settings.webdavConfiguredNo') }}
          · {{ t('settings.autoBackup') }}:
          {{ backupStatus.auto_backup_enabled ? t('settings.backupOn') : t('settings.backupOff') }}
        </p>
        <p v-if="backupStatus.local_auto_backups?.length" class="font-mono text-[10px] text-gray-400">
          {{ t('settings.localAutoBackups') }}:
          {{ backupStatus.local_auto_backups.map((b) => b.name).join(', ') }}
        </p>
      </div>
      <p class="text-xs text-amber-700 dark:text-amber-400/90">
        {{ t('settings.backupRestoreHint') }}
      </p>
    </div>
  </section>
</template>

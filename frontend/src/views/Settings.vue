<script setup lang="ts">
import GeneralSettings from '../components/settings/GeneralSettings.vue'
import TelegramApiSettings from '../components/settings/TelegramApiSettings.vue'
import AiSettings from '../components/settings/AiSettings.vue'
import BotNotifySettings from '../components/settings/BotNotifySettings.vue'
import DataManagementSettings from '../components/settings/DataManagementSettings.vue'
import AboutSettings from '../components/settings/AboutSettings.vue'
import { useSettingsPage } from '../composables/useSettingsPage'

const {
  t,
  settings,
  timezoneOptions,
  tgConfig,
  aiConfig,
  aiKeyDecryptFailed,
  loading,
  tgLoading,
  aiLoading,
  dataLoading,
  backupLoading,
  backupStatus,
  runtimeStatus,
  memoryStats,
  advancedLoading,
  botTestLoading,
  pageLoading,
  revealSecrets,
  isDirty,
  dirtyLabels,
  appVersion,
  versionLoading,
  checkLoading,
  versionBanner,
  botLoading,
  keepaliveLoading,
  saveAllLoading,
  webdavTestLoading,
  webdavListLoading,
  remoteWebdavFiles,
  remoteWebdavMessage,
  webdavPasswordSet,
  botTokenSet,
  remoteDownloadName,
  saveSettings,
  runKeepaliveNow,
  saveBotSettings,
  saveAdvancedSettings,
  saveAllSettings,
  testBot,
  saveTgConfig,
  resetTgConfig,
  saveAiConfig,
  testAi,
  handleExport,
  handleImportFile,
  handleBackupExport,
  handleWebdavTest,
  handleListRemoteBackups,
  handleDownloadRemoteBackup,
  handleCheckUpdate,
  toggleReveal,
} = useSettingsPage()
</script>

<template>
  <div class="max-w-7xl pb-10">
    <div
      v-if="isDirty && !pageLoading"
      class="sticky top-0 z-20 mb-4 flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-500/10 text-amber-800 dark:text-amber-200 shadow-sm"
      role="status"
    >
      <div class="min-w-0">
        <div>{{ t('settings.unsavedBanner') }}</div>
        <div v-if="dirtyLabels.length" class="mt-0.5 text-[10px] opacity-90">
          {{ t('settings.dirtySections') }}: {{ dirtyLabels.join(' · ') }}
        </div>
      </div>
      <button
        type="button"
        class="ui-btn-primary !px-3 !py-1.5 !text-xs shrink-0"
        :disabled="saveAllLoading || loading || botLoading || advancedLoading || tgLoading || aiLoading"
        @click="saveAllSettings"
      >
        {{ saveAllLoading ? t('settings.saving') : t('settings.saveAll') }}
      </button>
    </div>
    <div v-if="pageLoading" class="grid grid-cols-1 lg:grid-cols-2 gap-6" aria-busy="true">
      <div v-for="i in 4" :key="i" class="ui-card p-6 space-y-4">
        <div class="ui-skeleton h-5 w-32" />
        <div class="ui-skeleton h-3 w-48" />
        <div class="ui-skeleton h-10 w-full" />
        <div class="ui-skeleton h-10 w-full" />
        <div class="ui-skeleton h-10 w-2/3" />
      </div>
    </div>
    <div v-else class="grid grid-cols-1 lg:grid-cols-2 gap-6">

      <!-- 通用设置 + Telegram API（左列） -->
      <div class="flex flex-col gap-6">
        <GeneralSettings
          v-model="settings"
          :timezone-options="timezoneOptions"
          :loading="loading"
          :keepalive-loading="keepaliveLoading"
          @save="saveSettings"
          @run-keepalive="runKeepaliveNow"
        />
        <TelegramApiSettings
          v-model="tgConfig"
          :reveal="{ tgApiId: revealSecrets.tgApiId, tgApiHash: revealSecrets.tgApiHash }"
          :loading="tgLoading"
          @save="saveTgConfig"
          @reset="resetTgConfig"
          @toggle-reveal="toggleReveal"
        />
      </div>

      <!-- AI 配置 + Bot 通知（右列） -->
      <div class="flex flex-col gap-6">
        <AiSettings
          v-model:ai-model-value="aiConfig"
          v-model:settings-model-value="settings"
          :reveal="{ aiKey: revealSecrets.aiKey }"
          :ai-loading="aiLoading"
          :key-decrypt-failed="aiKeyDecryptFailed"
          @save-ai="saveAiConfig"
          @test-ai="testAi"
          @toggle-reveal="toggleReveal"
        />
        <BotNotifySettings
          v-model="settings"
          :bot-token-set="botTokenSet"
          :reveal="{ botToken: revealSecrets.botToken }"
          :bot-loading="botLoading"
          :bot-test-loading="botTestLoading"
          @save="saveBotSettings"
          @test="testBot"
          @toggle-reveal="toggleReveal"
        />
      </div>

      <!-- 数据管理（左列） -->
      <div class="flex flex-col gap-6">
        <DataManagementSettings
          v-model="settings"
          :webdav-password-set="webdavPasswordSet"
          :backup-status="backupStatus"
          :remote-files="remoteWebdavFiles"
          :remote-message="remoteWebdavMessage"
          :remote-download-name="remoteDownloadName"
          :data-loading="dataLoading"
          :backup-loading="backupLoading"
          :webdav-test-loading="webdavTestLoading"
          :webdav-list-loading="webdavListLoading"
          :advanced-loading="advancedLoading"
          @export-json="handleExport"
          @import-json="handleImportFile"
          @backup-export="handleBackupExport"
          @webdav-test="handleWebdavTest"
          @webdav-list="handleListRemoteBackups"
          @webdav-download="handleDownloadRemoteBackup"
          @save-advanced="saveAdvancedSettings"
        />
      </div>

      <!-- 关于 / 版本（右列） -->
      <div class="flex flex-col gap-6">
        <AboutSettings
          :app-version="appVersion"
          :runtime-status="runtimeStatus"
          :memory-stats="memoryStats"
          :version-banner="versionBanner"
          :version-loading="versionLoading"
          :check-loading="checkLoading"
          @check-update="handleCheckUpdate(true)"
        />
      </div>

    </div>
  </div>
</template>

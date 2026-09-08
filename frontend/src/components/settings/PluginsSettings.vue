<script setup lang="ts">
/**
 * 自定义插件概览与重载区块：
 * 展示当前系统已加载的 Action 插件清单、模式（reactive/active）、描述与源路径；
 * 提供「重新加载」按钮，触发服务端无感热重载。
 */
import { ref, onMounted } from 'vue'
import { Puzzle, RefreshCw, Folder, Info } from 'lucide-vue-next'
import { getPlugins, reloadPlugins, type PluginInfo } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'
import { useToast } from '../../composables/useToast'

const { t } = useI18n()
const toast = useToast()

const plugins = ref<PluginInfo[]>([])
const loading = ref(false)
const reloadLoading = ref(false)

const loadPluginList = async () => {
  loading.value = true
  try {
    plugins.value = await getPlugins()
  } catch {
    // 允许离线或降级
  } finally {
    loading.value = false
  }
}

const handleReload = async () => {
  reloadLoading.value = true
  try {
    const res = await reloadPlugins()
    plugins.value = res.plugins
    toast.success(t('settings.pluginsReloadSuccess', { count: res.count }))
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    toast.error(`${t('settings.pluginsReloadFailed')}: ${msg}`)
  } finally {
    reloadLoading.value = false
  }
}

onMounted(() => {
  void loadPluginList()
})
</script>

<template>
  <section class="ui-card p-6">
    <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-start justify-between gap-3">
      <div class="flex items-start gap-3 min-w-0">
        <span class="ui-section-icon" aria-hidden="true"><Puzzle class="w-3.5 h-3.5" /></span>
        <div class="min-w-0">
          <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.pluginsTitle') }}</h2>
          <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.pluginsDesc') }}</p>
        </div>
      </div>
      <button
        type="button"
        class="ui-btn-secondary shrink-0 !px-3 !py-1 !text-xs inline-flex items-center gap-1.5"
        :disabled="reloadLoading || loading"
        @click="handleReload"
      >
        <RefreshCw class="w-3.5 h-3.5" :class="reloadLoading ? 'animate-spin' : ''" />
        {{ reloadLoading ? t('settings.pluginsReloading') : t('settings.pluginsReload') }}
      </button>
    </div>

    <!-- 挂载目录与说明 -->
    <div class="mb-4 p-3 border border-sky-200/60 dark:border-sky-800/40 bg-sky-50/40 dark:bg-sky-500/5 text-xs text-gray-600 dark:text-gray-400 space-y-1">
      <div class="flex items-center gap-1.5 font-medium text-sky-700 dark:text-sky-300">
        <Folder class="w-3.5 h-3.5 shrink-0" />
        <span>{{ t('settings.pluginsMountTipTitle') }}</span>
      </div>
      <p class="text-[11px] leading-relaxed text-gray-500 dark:text-gray-400">
        {{ t('settings.pluginsMountTip') }}
      </p>
    </div>

    <!-- 插件清单 -->
    <div v-if="loading && !plugins.length" class="space-y-3">
      <div class="ui-skeleton h-12 w-full" />
      <div class="ui-skeleton h-12 w-full" />
    </div>

    <div v-else-if="!plugins.length" class="p-6 text-center border border-dashed border-gray-200 dark:border-gray-800 rounded text-xs text-gray-400">
      <Info class="w-5 h-5 mx-auto mb-2 text-gray-300 dark:text-gray-600" />
      <p>{{ t('settings.pluginsEmpty') }}</p>
    </div>

    <div v-else class="space-y-2.5">
      <div
        v-for="plugin in plugins"
        :key="plugin.name"
        class="p-3 border border-gray-100 dark:border-gray-800/60 bg-gray-50/60 dark:bg-white/[0.02] flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 text-xs transition-colors hover:border-gray-300 dark:hover:border-gray-700"
      >
        <div class="min-w-0 space-y-1">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="font-mono font-semibold text-gray-900 dark:text-gray-100 text-xs">
              {{ plugin.name }}
            </span>
            <span
              v-if="plugin.mode === 'reactive'"
              class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-sky-100 dark:bg-sky-950/80 text-sky-700 dark:text-sky-300 border border-sky-200 dark:border-sky-800/50"
            >
              {{ t('settings.pluginsReactive') }}
            </span>
            <span
              v-else
              class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-emerald-100 dark:bg-emerald-950/80 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/50"
            >
              {{ t('settings.pluginsActive') }}
            </span>
          </div>
          <p class="text-gray-600 dark:text-gray-300 text-[11px] leading-relaxed">
            {{ plugin.description || t('settings.pluginsNoDesc') }}
          </p>
          <div v-if="plugin.source_path" class="text-[10px] text-gray-400 dark:text-gray-500 font-mono truncate max-w-lg">
            {{ plugin.source_path }}
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

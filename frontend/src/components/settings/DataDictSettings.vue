<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { BookOpen, Plus, Trash2, Edit2, Play, Sparkles, X, RefreshCw, Layers, ChevronDown, Gauge, BarChart3 } from 'lucide-vue-next'
import { useI18n } from '../../composables/useI18n'
import { useToast } from '../../composables/useToast'
import { useAuthStore } from '../../stores/auth'
import { getLocalizedErrorMessage } from '../../lib/types'
import {
  listDataDicts,
  getDataDict,
  saveDataDict,
  deleteDataDict,
  sampleDataDictEntry,
  listBuiltinDataDicts,
  createDataDictFromBuiltin,
  getDataDictStats,
  type DataDictMeta,
  type BuiltinDataDictMeta,
  type DataDictStats,
} from '../../lib/api/data-dict'

const { t } = useI18n()
const { success, error } = useToast()
const authStore = useAuthStore()

const loading = ref(false)
const dicts = ref<DataDictMeta[]>([])
const builtins = ref<BuiltinDataDictMeta[]>([])
const builtinsLoading = ref(false)
const builtinsExpanded = ref(true)
const creatingBuiltin = ref('')
const expandedBuiltin = ref('')

/** 使用统计（接口失败时保持 null，UI 降级为「—」） */
const stats = ref<DataDictStats | null>(null)
const statsLoading = ref(false)

const availableBuiltins = computed(() => builtins.value.filter((item) => !item.exists))
const referencedBuiltinCount = computed(() => builtins.value.length - availableBuiltins.value.length)

/** 累计词条总数（来自已加载字典列表） */
const totalEntries = computed(() =>
  (Array.isArray(dicts.value) ? dicts.value : []).reduce(
    (sum, dict) => sum + (Number(dict.count) || 0),
    0,
  ),
)
/** 从未被抽取过的字典数量 */
const unusedDictCount = computed(() => {
  if (!stats.value) return 0
  return (Array.isArray(dicts.value) ? dicts.value : []).filter(
    (dict) => !stats.value?.dicts?.[dict.name]?.count,
  ).length
})
const usageOf = (name: string): number | null => {
  const value = stats.value?.dicts?.[name]?.count
  return typeof value === 'number' ? value : null
}

const dictQuery = ref('')
const filteredDicts = computed(() => {
  const list = Array.isArray(dicts.value) ? dicts.value : []
  const query = dictQuery.value.trim().toLowerCase()
  if (!query) return list
  return list.filter(
    (dict) =>
      dict.name.toLowerCase().includes(query) ||
      (dict.remark || '').toLowerCase().includes(query),
  )
})

// Modal / Drawer state
const showModal = ref(false)
const isEditing = ref(false)
const saving = ref(false)
const formName = ref('')
const formRemark = ref('')
const formEntries = ref('')
const formError = ref('')

// Sample Preview state
const showSampleModal = ref(false)
const sampleDictName = ref('')
const sampleMode = ref<'random' | 'round_robin'>('random')
const sampleResult = ref('')
const sampling = ref(false)

const loadDicts = async () => {
  const token = authStore.token
  if (!token) return
  loading.value = true
  try {
    dicts.value = await listDataDicts(token)
  } catch (err: unknown) {
    error(getLocalizedErrorMessage(err, t, t('common.loadFailed')))
  } finally {
    loading.value = false
  }
}

const loadStats = async () => {
  const token = authStore.token
  if (!token) return
  statsLoading.value = true
  try {
    stats.value = await getDataDictStats(token)
  } catch {
    // 统计失败不阻塞字典管理，指标降级显示
    stats.value = null
  } finally {
    statsLoading.value = false
  }
}

const loadBuiltins = async () => {
  const token = authStore.token
  if (!token) return
  builtinsLoading.value = true
  try {
    const list = await listBuiltinDataDicts(token)
    builtins.value = Array.isArray(list) ? list : []
  } catch (err: unknown) {
    error(getLocalizedErrorMessage(err, t, t('common.loadFailed')))
  } finally {
    builtinsLoading.value = false
  }
}

const handleCreateFromBuiltin = async (name: string) => {
  const token = authStore.token
  if (!token) return
  creatingBuiltin.value = name
  try {
    await createDataDictFromBuiltin(token, name)
    success(t('settings.dataDictBuiltinCreateSuccess', { name }))
    if (expandedBuiltin.value === name) expandedBuiltin.value = ''
    await Promise.all([loadDicts(), loadBuiltins(), loadStats()])
  } catch (err: unknown) {
    error(getLocalizedErrorMessage(err, t, t('common.loadFailed')))
  } finally {
    creatingBuiltin.value = ''
  }
}

const toggleBuiltinEntries = (name: string) => {
  expandedBuiltin.value = expandedBuiltin.value === name ? '' : name
}

const toggleBuiltins = () => {
  builtinsExpanded.value = !builtinsExpanded.value
}

const openCreateModal = () => {
  isEditing.value = false
  formName.value = ''
  formRemark.value = ''
  formEntries.value = ''
  formError.value = ''
  showModal.value = true
}

const openEditModal = async (name: string) => {
  const token = authStore.token
  if (!token) return
  isEditing.value = true
  formName.value = name
  formRemark.value = ''
  formEntries.value = ''
  formError.value = ''
  showModal.value = true
  saving.value = true

  try {
    const detail = await getDataDict(token, name)
    formRemark.value = detail.remark || ''
    formEntries.value = (detail.entries || []).join('\n')
  } catch (err: unknown) {
    error(getLocalizedErrorMessage(err, t, t('common.loadFailed')))
    showModal.value = false
  } finally {
    saving.value = false
  }
}

const handleSave = async () => {
  const token = authStore.token
  if (!token) return

  const trimmedName = formName.value.trim()
  if (!trimmedName) {
    formError.value = t('settings.dataDictNamePlaceholder')
    return
  }
  if (!/^[a-zA-Z0-9_-]+$/.test(trimmedName)) {
    formError.value = t('settings.dataDictNamePlaceholder')
    return
  }

  const lines = formEntries.value
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)

  if (lines.length === 0) {
    formError.value = t('settings.dataDictEntriesPlaceholder')
    return
  }

  saving.value = true
  formError.value = ''
  try {
    await saveDataDict(token, {
      name: trimmedName,
      remark: formRemark.value.trim(),
      entries: lines,
    })
    success(t('settings.dataDictSaveSuccess'))
    showModal.value = false
    await Promise.all([loadDicts(), loadBuiltins(), loadStats()])
  } catch (err: unknown) {
    formError.value = getLocalizedErrorMessage(err, t, t('settings.saveFailed'))
  } finally {
    saving.value = false
  }
}

const handleDelete = async (name: string) => {
  const confirmMsg = t('settings.dataDictDeleteConfirm', { name })
  if (!window.confirm(confirmMsg)) return

  const token = authStore.token
  if (!token) return

  loading.value = true
  try {
    await deleteDataDict(token, name)
    success(t('settings.dataDictDeleteSuccess'))
    await Promise.all([loadDicts(), loadBuiltins(), loadStats()])
  } catch (err: unknown) {
    error(getLocalizedErrorMessage(err, t, t('tasks.deleteFailed')))
  } finally {
    loading.value = false
  }
}

const openSampleModal = (name: string) => {
  sampleDictName.value = name
  sampleMode.value = 'random'
  sampleResult.value = ''
  showSampleModal.value = true
  runSample()
}

const runSample = async () => {
  const token = authStore.token
  if (!token || !sampleDictName.value) return

  sampling.value = true
  try {
    const res = await sampleDataDictEntry(token, sampleDictName.value, sampleMode.value)
    sampleResult.value = res.entry
  } catch (err: unknown) {
    error(getLocalizedErrorMessage(err, t, t('tasks.triggerFailed')))
  } finally {
    sampling.value = false
  }
}

onMounted(() => {
  loadDicts()
  loadBuiltins()
  loadStats()
})
</script>

<template>
  <section class="ui-card p-6">
    <div class="mb-6 border-b border-[var(--sp-border)] pb-3 flex items-center justify-between gap-3">
      <div class="flex items-start gap-3 min-w-0">
        <span class="ui-section-icon" aria-hidden="true">
          <BookOpen class="w-3.5 h-3.5" />
        </span>
        <div class="min-w-0">
          <h2 class="text-base font-medium text-[var(--sp-text)] font-semibold">
            {{ t('settings.dataDict') }}
          </h2>
          <p class="text-[10px] text-[var(--sp-text-muted)] mt-1">
            {{ t('settings.dataDictDesc') }}
          </p>
        </div>
      </div>
      <button
        type="button"
        class="ui-btn-primary !px-2.5 !py-1.5 !text-xs flex items-center gap-1.5 shrink-0"
        @click="openCreateModal"
      >
        <Plus class="w-3.5 h-3.5" />
        <span>{{ t('settings.dataDictAdd') }}</span>
      </button>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-5 lg:gap-6 items-start">
      <!-- 左栏：使用概览 + 内置字典 -->
      <div class="min-w-0 space-y-4">
        <div class="grid grid-cols-3 gap-2">
          <div class="p-2.5 rounded-[var(--sp-radius)] border border-[var(--sp-border)] bg-[var(--sp-surface-subtle)] dark:bg-[var(--sp-surface-muted)] min-w-0">
            <div class="flex items-center gap-1 text-[10px] text-[var(--sp-text-muted)]">
              <BarChart3 class="w-3 h-3 shrink-0" aria-hidden="true" />
              <span class="truncate">{{ t('settings.dataDictStatsDicts') }}</span>
            </div>
            <div class="mt-1 text-base font-semibold text-[var(--sp-text)] tabular-nums">{{ dicts.length || 0 }}</div>
          </div>
          <div class="p-2.5 rounded-[var(--sp-radius)] border border-[var(--sp-border)] bg-[var(--sp-surface-subtle)] dark:bg-[var(--sp-surface-muted)] min-w-0">
            <div class="flex items-center gap-1 text-[10px] text-[var(--sp-text-muted)]">
              <Layers class="w-3 h-3 shrink-0" aria-hidden="true" />
              <span class="truncate">{{ t('settings.dataDictStatsEntries') }}</span>
            </div>
            <div class="mt-1 text-base font-semibold text-[var(--sp-text)] tabular-nums">{{ totalEntries }}</div>
          </div>
          <div class="p-2.5 rounded-[var(--sp-radius)] border border-[var(--sp-border)] bg-[var(--sp-surface-subtle)] dark:bg-[var(--sp-surface-muted)] min-w-0">
            <div class="flex items-center gap-1 text-[10px] text-[var(--sp-text-muted)]">
              <Gauge class="w-3 h-3 shrink-0" aria-hidden="true" />
              <span class="truncate">{{ t('settings.dataDictStatsDraws') }}</span>
            </div>
            <div class="mt-1 text-base font-semibold text-[var(--sp-text)] tabular-nums">
              <span v-if="stats">{{ stats.total }}</span>
              <span v-else-if="statsLoading" class="text-[var(--sp-text-muted)]">…</span>
              <span v-else class="text-[var(--sp-text-muted)]" :title="t('settings.dataDictStatsLoadFailed')">—</span>
            </div>
          </div>
        </div>
        <p v-if="stats && unusedDictCount > 0" class="text-[10px] text-[var(--sp-text-muted)] -mt-1">
          {{ t('settings.dataDictUsageNever') }}: {{ unusedDictCount }}
        </p>

    <!-- Built-in presets -->
    <div class="mb-4 p-3.5 border border-dashed border-[var(--sp-border)] dark:border-[var(--sp-border)] rounded-[var(--sp-radius-lg)] bg-[var(--sp-surface)]/[0.03]">
      <button
        type="button"
        class="w-full flex items-center gap-1.5 text-xs text-[var(--sp-text-secondary)] dark:text-[var(--sp-text-secondary)] font-medium text-left"
        :aria-expanded="builtinsExpanded"
        aria-controls="builtin-dict-panel"
        @click="toggleBuiltins"
      >
        <Sparkles class="w-3.5 h-3.5 text-amber-500 shrink-0" />
        <span class="shrink-0">{{ t('settings.dataDictBuiltin') }}</span>
        <span
          v-if="referencedBuiltinCount > 0"
          class="px-1.5 py-0.5 text-[10px] rounded-full bg-emerald-100 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 shrink-0"
        >
          {{ t('settings.dataDictBuiltinReferenced', { count: referencedBuiltinCount }) }}
        </span>
        <span class="min-w-0 flex-1 text-[10px] text-[var(--sp-text-muted)] font-normal truncate">
          ({{ t('settings.dataDictBuiltinHint') }})
        </span>
        <ChevronDown
          class="w-3.5 h-3.5 shrink-0 text-[var(--sp-text-muted)] transition-transform"
          :class="builtinsExpanded ? '' : '-rotate-90'"
          aria-hidden="true"
        />
      </button>

      <div v-show="builtinsExpanded" id="builtin-dict-panel">
        <div v-if="builtinsLoading && builtins.length === 0" class="py-3 text-center text-xs text-[var(--sp-text-muted)]">
          <RefreshCw class="w-3.5 h-3.5 animate-spin mx-auto mb-1.5 opacity-60" />
          {{ t('common.loading') }}
        </div>

        <div
          v-else-if="builtins.length > 0 && availableBuiltins.length === 0"
          class="mt-2.5 px-3 py-2 text-[11px] text-[var(--sp-text-muted)] border border-dashed border-[var(--sp-border)] rounded-[var(--sp-radius)] text-center"
        >
          {{ t('settings.dataDictBuiltinAllReferenced') }}
        </div>

        <div v-else class="mt-2.5 space-y-2">
          <div
            v-for="item in availableBuiltins"
            :key="item.name"
            class="border border-[var(--sp-border)] dark:border-[var(--sp-border)] rounded-[var(--sp-radius)] overflow-hidden"
          >
            <div class="flex items-center justify-between gap-3 px-3 py-2 bg-[var(--sp-surface-subtle)] dark:bg-[var(--sp-surface-muted)]">
              <button
                type="button"
                class="min-w-0 flex-1 flex items-center gap-2 text-left"
                :aria-expanded="expandedBuiltin === item.name"
                :aria-controls="`builtin-entries-${item.name}`"
                @click="toggleBuiltinEntries(item.name)"
              >
                <span class="font-mono font-semibold text-sm text-sky-600 dark:text-sky-400">{{ item.name }}</span>
                <span class="px-2 py-0.5 text-[11px] rounded-full bg-amber-100 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 shrink-0">
                  {{ t('settings.dataDictCount', { count: item.count }) }}
                </span>
                <span class="hidden sm:inline text-[11px] text-[var(--sp-text-muted)] truncate">{{ item.remark }}</span>
              </button>
              <button
                type="button"
                class="ui-btn-primary !px-2.5 !py-1 !text-[11px] flex items-center gap-1 shrink-0"
                :disabled="creatingBuiltin === item.name"
                @click="handleCreateFromBuiltin(item.name)"
              >
                <Plus class="w-3 h-3" />
                <span>{{ t('settings.dataDictBuiltinAdd') }}</span>
              </button>
            </div>
            <div v-if="expandedBuiltin === item.name" :id="`builtin-entries-${item.name}`" class="px-3 py-2 border-t border-[var(--sp-border)] dark:border-[var(--sp-border)]">
              <div class="flex flex-wrap gap-1.5">
                <span
                  v-for="entry in item.entries"
                  :key="entry"
                  class="px-2 py-0.5 text-[11px] rounded-[var(--sp-radius)] bg-[var(--sp-surface-subtle)] dark:bg-[var(--sp-surface-muted)] text-[var(--sp-text-secondary)] dark:text-[var(--sp-text-secondary)] border border-[var(--sp-border)] dark:border-[var(--sp-border)]"
                >
                  {{ entry }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

      </div>

      <!-- 右栏：我的字典 -->
      <div class="min-w-0">
    <!-- Dicts list -->
    <div class="mt-1 mb-2 flex items-center justify-between gap-2">
      <h3 class="min-w-0 truncate text-xs font-medium text-[var(--sp-text-secondary)] dark:text-[var(--sp-text-secondary)]">
        {{ t('settings.dataDictListTitle') }}
        <span class="ml-1 text-[10px] font-normal text-[var(--sp-text-muted)]">
          {{ t('settings.dataDictListSummary', { count: dicts.length || 0 }) }}
        </span>
      </h3>
      <input
        v-if="(dicts.length || 0) > 5"
        v-model="dictQuery"
        type="text"
        class="ui-input !h-7 !px-2 !text-[11px] !w-24 sm:!w-36 shrink-0"
        :placeholder="t('settings.dataDictSearchPlaceholder')"
        :aria-label="t('settings.dataDictSearchPlaceholder')"
      >
    </div>

    <div v-if="loading && dicts.length === 0" class="py-6 text-center text-xs text-[var(--sp-text-muted)]">
      <RefreshCw class="w-4 h-4 animate-spin mx-auto mb-2 opacity-60" />
      {{ t('common.loading') }}
    </div>

    <div v-else-if="dicts.length === 0" class="py-8 text-center text-xs text-[var(--sp-text-muted)] dark:text-[var(--sp-text-secondary)] border border-dashed border-[var(--sp-border)] dark:border-[var(--sp-border)] rounded-[var(--sp-radius-lg)]">
      <Layers class="w-6 h-6 mx-auto mb-2 text-[var(--sp-text-muted)] dark:text-[var(--sp-text-secondary)]" />
      {{ t('settings.dataDictEmpty') }}
    </div>

    <div v-else-if="filteredDicts.length === 0" class="py-6 text-center text-xs text-[var(--sp-text-muted)] border border-dashed border-[var(--sp-border)] rounded-[var(--sp-radius-lg)]">
      {{ t('settings.dataDictSearchEmpty') }}
    </div>

    <div v-else class="max-h-[min(60vh,420px)] overflow-y-auto pr-1 -mr-1 space-y-3">
      <div
        v-for="dict in filteredDicts"
        :key="dict.name"
        class="p-3.5 border border-[var(--sp-border)] dark:border-[var(--sp-border)] rounded-[var(--sp-radius-lg)] bg-[var(--sp-surface-subtle)] dark:bg-[var(--sp-surface-muted)] hover:border-[var(--sp-border-strong)] dark:border-[var(--sp-border)] transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-3"
      >
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="font-mono font-semibold text-sm text-sky-600 dark:text-sky-400">
              {{ dict.name }}
            </span>
            <span class="px-2 py-0.5 text-[11px] rounded-full bg-sky-100 dark:bg-sky-950/60 text-sky-700 dark:text-sky-300">
              {{ t('settings.dataDictCount', { count: dict.count }) }}
            </span>
            <span
              v-if="(usageOf(dict.name) ?? 0) > 0"
              class="px-2 py-0.5 text-[11px] rounded-full bg-emerald-100 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300"
              :title="t('settings.dataDictStatsDraws')"
            >
              {{ t('settings.dataDictUsage', { count: usageOf(dict.name) }) }}
            </span>
            <span
              v-else-if="stats"
              class="px-2 py-0.5 text-[11px] rounded-full bg-[var(--sp-surface-muted)] text-[var(--sp-text-muted)] border border-[var(--sp-border)]"
            >
              {{ t('settings.dataDictUsageNever') }}
            </span>
            <span v-if="dict.updated_at" class="text-[10px] text-[var(--sp-text-muted)]">
              {{ dict.updated_at.replace('T', ' ').slice(0, 19) }}
            </span>
          </div>
          <p v-if="dict.remark" class="text-xs text-[var(--sp-text-secondary)] dark:text-[var(--sp-text-secondary)] mt-1 truncate">
            {{ dict.remark }}
          </p>
          <div class="mt-1 text-[11px] font-mono text-[var(--sp-text-muted)] dark:text-[var(--sp-text-secondary)] select-all">
            &#123;dict:{{ dict.name }}&#125; &middot; &#123;dict:{{ dict.name }}:round_robin&#125;
          </div>
        </div>

        <div class="flex items-center gap-1.5 shrink-0 self-end sm:self-center">
          <button
            type="button"
            class="ui-btn-secondary !p-1.5 !text-xs text-[var(--sp-text-secondary)] dark:text-[var(--sp-text-secondary)] hover:text-sky-600 dark:hover:text-sky-400"
            :title="t('settings.dataDictSample')"
            @click="openSampleModal(dict.name)"
          >
            <Sparkles class="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            class="ui-btn-secondary !p-1.5 !text-xs text-[var(--sp-text-secondary)] dark:text-[var(--sp-text-secondary)] hover:text-emerald-600 dark:hover:text-emerald-400"
            :title="t('settings.dataDictEdit')"
            @click="openEditModal(dict.name)"
          >
            <Edit2 class="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            class="ui-btn-secondary !p-1.5 !text-xs text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40"
            :title="t('tasks.delete')"
            @click="handleDelete(dict.name)"
          >
            <Trash2 class="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>

      </div>
    </div>

    <!-- Edit/Add Modal -->
    <div
      v-if="showModal"
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs"
      role="dialog"
      aria-modal="true"
    >
      <div class="ui-card w-full max-w-lg p-6 space-y-4 shadow-xl border border-[var(--sp-border)] dark:border-[var(--sp-border)]">
        <div class="flex items-center justify-between border-b border-[var(--sp-border)] dark:border-[var(--sp-border)] pb-3">
          <h3 class="text-sm font-semibold text-[var(--sp-text)] font-semibold">
            {{ isEditing ? t('settings.dataDictEdit') : t('settings.dataDictAdd') }}
          </h3>
          <button
            type="button"
            class="text-[var(--sp-text-muted)] hover:text-[var(--sp-text-secondary)] dark:hover:text-[var(--sp-text)]"
            @click="showModal = false"
          >
            <X class="w-4 h-4" />
          </button>
        </div>

        <div v-if="formError" class="p-2.5 text-xs rounded bg-rose-50 dark:bg-rose-950/50 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-900">
          {{ formError }}
        </div>

        <div class="space-y-3">
          <div class="space-y-1">
            <label class="ui-label" for="dict-name">{{ t('settings.dataDictName') }}</label>
            <input
              id="dict-name"
              v-model="formName"
              type="text"
              class="ui-input font-mono text-sm"
              :placeholder="t('settings.dataDictNamePlaceholder')"
              :disabled="isEditing"
            >
          </div>

          <div class="space-y-1">
            <label class="ui-label" for="dict-remark">{{ t('settings.dataDictRemark') }}</label>
            <input
              id="dict-remark"
              v-model="formRemark"
              type="text"
              class="ui-input text-sm"
              :placeholder="t('settings.dataDictRemarkPlaceholder')"
            >
          </div>

          <div class="space-y-1">
            <div class="flex justify-between items-center">
              <label class="ui-label" for="dict-entries">{{ t('settings.dataDictEntries') }}</label>
              <span class="text-[11px] text-[var(--sp-text-muted)]">
                {{ t('settings.dataDictEntryLines', { count: formEntries.split('\n').filter(s => s.trim()).length }) }}
              </span>
            </div>
            <textarea
              id="dict-entries"
              v-model="formEntries"
              rows="6"
              class="ui-input text-xs font-mono resize-y"
              :placeholder="t('settings.dataDictEntriesPlaceholder')"
            />
            <p class="text-[11px] text-[var(--sp-text-muted)] mt-1">
              {{ t('settings.dataDictMacroHint', { name: formName || 'name' }) }}
            </p>
          </div>
        </div>

        <div class="flex justify-end gap-2 pt-2 border-t border-[var(--sp-border)] dark:border-[var(--sp-border)]">
          <button
            type="button"
            class="ui-btn-secondary !px-4 !py-1.5 !text-xs"
            :disabled="saving"
            @click="showModal = false"
          >
            {{ t('common.cancel') }}
          </button>
          <button
            type="button"
            class="ui-btn-primary !px-4 !py-1.5 !text-xs"
            :disabled="saving"
            @click="handleSave"
          >
            {{ saving ? t('common.saving') : t('common.save') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Sample Preview Modal -->
    <div
      v-if="showSampleModal"
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs"
      role="dialog"
      aria-modal="true"
    >
      <div class="ui-card w-full max-w-md p-6 space-y-4 shadow-xl border border-[var(--sp-border)] dark:border-[var(--sp-border)]">
        <div class="flex items-center justify-between border-b border-[var(--sp-border)] dark:border-[var(--sp-border)] pb-3">
          <div class="flex items-center gap-2">
            <Sparkles class="w-4 h-4 text-sky-500" />
            <h3 class="text-sm font-semibold text-[var(--sp-text)] font-semibold">
              {{ t('settings.dataDictSample') }} - {{ sampleDictName }}
            </h3>
          </div>
          <button
            type="button"
            class="text-[var(--sp-text-muted)] hover:text-[var(--sp-text-secondary)] dark:hover:text-[var(--sp-text)]"
            @click="showSampleModal = false"
          >
            <X class="w-4 h-4" />
          </button>
        </div>

        <div class="flex items-center gap-4 text-xs">
          <label class="flex items-center gap-1.5 cursor-pointer">
            <input
              v-model="sampleMode"
              type="radio"
              value="random"
              class="accent-sky-500"
              @change="runSample"
            >
            <span>{{ t('settings.dataDictSampleRandom') }}</span>
          </label>
          <label class="flex items-center gap-1.5 cursor-pointer">
            <input
              v-model="sampleMode"
              type="radio"
              value="round_robin"
              class="accent-sky-500"
              @change="runSample"
            >
            <span>{{ t('settings.dataDictSampleRoundRobin') }}</span>
          </label>
        </div>

        <div class="p-3.5 rounded-[var(--sp-radius-lg)] bg-[var(--sp-surface-subtle)] dark:bg-[var(--sp-surface-muted)] border border-[var(--sp-border)] dark:border-[var(--sp-border)] min-h-[4rem] flex flex-col justify-center">
          <div v-if="sampling" class="flex items-center gap-2 text-xs text-[var(--sp-text-muted)]">
            <RefreshCw class="w-3.5 h-3.5 animate-spin" />
            {{ t('common.loading') }}
          </div>
          <div v-else-if="sampleResult" class="text-xs font-medium text-[var(--sp-text-secondary)] dark:text-[var(--sp-text)] whitespace-pre-wrap break-words">
            {{ sampleResult }}
          </div>
          <div v-else class="text-xs text-[var(--sp-text-muted)]">
            {{ t('common.noData') }}
          </div>
        </div>

        <div class="flex justify-end gap-2 pt-2 border-t border-[var(--sp-border)] dark:border-[var(--sp-border)]">
          <button
            type="button"
            class="ui-btn-secondary !px-4 !py-1.5 !text-xs"
            @click="showSampleModal = false"
          >
            {{ t('common.close') }}
          </button>
          <button
            type="button"
            class="ui-btn-primary !px-4 !py-1.5 !text-xs flex items-center gap-1"
            :disabled="sampling"
            @click="runSample"
          >
            <Play class="w-3 h-3" />
            <span>{{ t('settings.dataDictSample') }}</span>
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

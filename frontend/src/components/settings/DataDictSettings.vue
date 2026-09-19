<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { BookOpen, Plus, Trash2, Edit2, Play, Sparkles, X, RefreshCw, Layers } from 'lucide-vue-next'
import { useI18n } from '../../composables/useI18n'
import { useToast } from '../../composables/useToast'
import { useAuthStore } from '../../stores/auth'
import {
  listDataDicts,
  getDataDict,
  saveDataDict,
  deleteDataDict,
  sampleDataDictEntry,
  type DataDictMeta,
} from '../../lib/api/data-dict'

const { t } = useI18n()
const { success, error } = useToast()
const authStore = useAuthStore()

const loading = ref(false)
const dicts = ref<DataDictMeta[]>([])

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
  } catch (err: any) {
    error(err?.message || t('common.loadFailed'))
  } finally {
    loading.value = false
  }
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
  } catch (err: any) {
    error(err?.message || t('common.loadFailed'))
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
    await loadDicts()
  } catch (err: any) {
    formError.value = err?.message || t('settings.saveFailed')
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
    await loadDicts()
  } catch (err: any) {
    error(err?.message || t('tasks.deleteFailed'))
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
  } catch (err: any) {
    error(err?.message || t('tasks.triggerFailed'))
  } finally {
    sampling.value = false
  }
}

onMounted(() => {
  loadDicts()
})
</script>

<template>
  <section class="ui-card p-6">
    <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-center justify-between gap-3">
      <div class="flex items-start gap-3 min-w-0">
        <span class="ui-section-icon" aria-hidden="true">
          <BookOpen class="w-3.5 h-3.5" />
        </span>
        <div class="min-w-0">
          <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">
            {{ t('settings.dataDict') }}
          </h2>
          <p class="text-[10px] text-gray-500 mt-1">
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

    <!-- Dicts list -->
    <div v-if="loading && dicts.length === 0" class="py-6 text-center text-xs text-gray-400">
      <RefreshCw class="w-4 h-4 animate-spin mx-auto mb-2 opacity-60" />
      {{ t('common.loading') }}
    </div>

    <div v-else-if="dicts.length === 0" class="py-8 text-center text-xs text-gray-400 dark:text-gray-500 border border-dashed border-gray-200 dark:border-gray-800 rounded-lg">
      <Layers class="w-6 h-6 mx-auto mb-2 text-gray-300 dark:text-gray-600" />
      {{ t('settings.dataDictEmpty') }}
    </div>

    <div v-else class="space-y-3">
      <div
        v-for="dict in dicts"
        :key="dict.name"
        class="p-3.5 border border-gray-200 dark:border-gray-800 rounded-lg bg-gray-50/50 dark:bg-gray-800/30 hover:border-gray-300 dark:hover:border-gray-700 transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-3"
      >
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="font-mono font-semibold text-sm text-sky-600 dark:text-sky-400">
              {{ dict.name }}
            </span>
            <span class="px-2 py-0.5 text-[11px] rounded-full bg-sky-100 dark:bg-sky-950/60 text-sky-700 dark:text-sky-300">
              {{ t('settings.dataDictCount', { count: dict.count }) }}
            </span>
            <span v-if="dict.updated_at" class="text-[10px] text-gray-400">
              {{ dict.updated_at.replace('T', ' ').slice(0, 19) }}
            </span>
          </div>
          <p v-if="dict.remark" class="text-xs text-gray-600 dark:text-gray-400 mt-1 truncate">
            {{ dict.remark }}
          </p>
          <div class="mt-1 text-[11px] font-mono text-gray-400 dark:text-gray-500 select-all">
            &#123;dict:{{ dict.name }}&#125; &middot; &#123;dict:{{ dict.name }}:round_robin&#125;
          </div>
        </div>

        <div class="flex items-center gap-1.5 shrink-0 self-end sm:self-center">
          <button
            type="button"
            class="ui-btn-secondary !p-1.5 !text-xs text-gray-600 dark:text-gray-300 hover:text-sky-600 dark:hover:text-sky-400"
            :title="t('settings.dataDictSample')"
            @click="openSampleModal(dict.name)"
          >
            <Sparkles class="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            class="ui-btn-secondary !p-1.5 !text-xs text-gray-600 dark:text-gray-300 hover:text-emerald-600 dark:hover:text-emerald-400"
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

    <!-- Edit/Add Modal -->
    <div
      v-if="showModal"
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs"
      role="dialog"
      aria-modal="true"
    >
      <div class="ui-card w-full max-w-lg p-6 space-y-4 shadow-xl border border-gray-200 dark:border-gray-700">
        <div class="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 pb-3">
          <h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100">
            {{ isEditing ? t('settings.dataDictEdit') : t('settings.dataDictAdd') }}
          </h3>
          <button
            type="button"
            class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
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
              <span class="text-[11px] text-gray-400">
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
            <p class="text-[11px] text-gray-500 mt-1">
              {{ t('settings.dataDictMacroHint', { name: formName || 'name' }) }}
            </p>
          </div>
        </div>

        <div class="flex justify-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-800">
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
      <div class="ui-card w-full max-w-md p-6 space-y-4 shadow-xl border border-gray-200 dark:border-gray-700">
        <div class="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 pb-3">
          <div class="flex items-center gap-2">
            <Sparkles class="w-4 h-4 text-sky-500" />
            <h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100">
              {{ t('settings.dataDictSample') }} - {{ sampleDictName }}
            </h3>
          </div>
          <button
            type="button"
            class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
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

        <div class="p-3.5 rounded-lg bg-gray-50 dark:bg-gray-800/60 border border-gray-200 dark:border-gray-700/80 min-h-[4rem] flex flex-col justify-center">
          <div v-if="sampling" class="flex items-center gap-2 text-xs text-gray-400">
            <RefreshCw class="w-3.5 h-3.5 animate-spin" />
            {{ t('common.loading') }}
          </div>
          <div v-else-if="sampleResult" class="text-xs font-medium text-gray-800 dark:text-gray-200 whitespace-pre-wrap break-words">
            {{ sampleResult }}
          </div>
          <div v-else class="text-xs text-gray-400">
            {{ t('common.noData') }}
          </div>
        </div>

        <div class="flex justify-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-800">
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

<script setup lang="ts">
/**
 * 任务表单：动作序列编辑区块（支持拖拽排序、高级管道容错与宏变量注入）。
 */
import { ref, computed, onMounted } from 'vue'
import {
  Plus,
  Trash2,
  ArrowUp,
  ArrowDown,
  GripVertical,
  SlidersHorizontal,
  Sparkles,
  Play,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Clock,
} from 'lucide-vue-next'
import Modal from '../Modal.vue'
import CustomSelect from '../CustomSelect.vue'
import type { TaskActionItem } from '../../lib/types'
import { useI18n } from '../../composables/useI18n'
import { getPlugins, testPlugin, type PluginInfo, type PluginTestResponse } from '../../lib/api'
import { withToken } from '../../lib/api/core'

const { t } = useI18n()

// 动作插件在线调试状态
const isActionDebugModalOpen = ref(false)
const debugAction = ref<TaskActionItem | null>(null)
const debugPluginInfo = ref<PluginInfo | null>(null)
const debugInputText = ref('')
const debugParams = ref<Record<string, unknown>>({})
const debugRunning = ref(false)
const debugResult = ref<PluginTestResponse | null>(null)

const openDebugModalForAction = (action: TaskActionItem) => {
  debugAction.value = action
  debugPluginInfo.value = getPluginInfo(action.value) || null
  debugResult.value = null
  debugInputText.value = ''
  debugParams.value = JSON.parse(JSON.stringify(action.params || {}))
  isActionDebugModalOpen.value = true
}

const applyDebugParamsToAction = () => {
  if (debugAction.value) {
    debugAction.value.params = JSON.parse(JSON.stringify(debugParams.value))
    isActionDebugModalOpen.value = false
  }
}

const runActionPluginTest = async () => {
  if (!debugAction.value?.value) return
  debugRunning.value = true
  debugResult.value = null
  try {
    const res = await withToken((token) =>
      testPlugin(
        String(debugAction.value!.value),
        {
          text: debugInputText.value,
          params: debugParams.value,
          // 与任务正式执行一致：带上动作配置的超时
          timeout: debugAction.value.timeout ?? undefined,
        },
        token,
      ),
    )
    if (res) debugResult.value = res
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    debugResult.value = {
      name: String(debugAction.value!.value),
      success: false,
      handled: false,
      error: msg,
      logs: [`[error] ${msg}`],
      duration_ms: 0,
    }
  } finally {
    debugRunning.value = false
  }
}

const availablePlugins = ref<PluginInfo[]>([])
const manualPluginMode = ref<Record<number, boolean>>({})
const expandedAdvanced = ref<Record<number, boolean>>({})
const draggedIdx = ref<number | null>(null)
const dragOverIdx = ref<number | null>(null)

const toggleAdvanced = (actionId: number) => {
  expandedAdvanced.value[actionId] = !expandedAdvanced.value[actionId]
}

const onDragStart = (idx: number, e: DragEvent) => {
  draggedIdx.value = idx
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(idx))
  }
}

const onDragOver = (idx: number, e: DragEvent) => {
  e.preventDefault()
  dragOverIdx.value = idx
}

const onDragLeave = () => {
  dragOverIdx.value = null
}

const onDrop = (targetIdx: number) => {
  if (draggedIdx.value !== null && draggedIdx.value !== targetIdx) {
    emit('reorder', draggedIdx.value, targetIdx)
  }
  draggedIdx.value = null
  dragOverIdx.value = null
}

const MACRO_PRESETS = [
  { label: '{{ date }}', desc: '当前日期 (YYYY-MM-DD)' },
  { label: '{{ time }}', desc: '当前时间 (HH:MM:SS)' },
  { label: '{{ prev_output }}', desc: '上一动作产出' },
  { label: '{{ random_int(1, 100) }}', desc: '随机整数' },
  { label: '{{ account.name }}', desc: '当前账号名' },
]

const insertMacro = (action: TaskActionItem, macro: string) => {
  if (action.type === 'send_text' || action.type === 'click_text_button') {
    action.value = (action.value || '') + macro
  } else if (['vision_send', 'vision_click', 'calc_send', 'calc_click'].includes(action.type)) {
    action.aiPrompt = (action.aiPrompt || '') + macro
  }
}

onMounted(async () => {
  try {
    availablePlugins.value = await withToken((token) => getPlugins(token)) ?? []
  } catch {
    // 降级为空列表
  }
})

const getPluginInfo = (name?: string) => {
  if (!name) return null
  return availablePlugins.value.find(p => p.name === name) || null
}

const getParamValue = (action: TaskActionItem, key: string, fallback: unknown) => {
  if (!action.params) return fallback
  return action.params[key] !== undefined ? action.params[key] : fallback
}

const setParamValue = (action: TaskActionItem, key: string, val: unknown) => {
  if (!action.params) {
    action.params = {}
  }
  action.params[key] = val
}

// 预设骰子/游戏表情
const DICE_PRESETS = [
  { label: '🎲 骰子 (Dice)', value: '🎲' },
  { label: '🎯 飞镖 (Dart)', value: '🎯' },
  { label: '🏀 篮球 (Basketball)', value: '🏀' },
  { label: '⚽ 足球 (Football)', value: '⚽' },
  { label: '🎳 保龄球 (Bowling)', value: '🎳' },
  { label: '🎰 老虎机 (Slot)', value: '🎰' },
]

const diceSelectOptions = computed(() => [
  ...DICE_PRESETS,
  { label: t('taskForm.diceCustom'), value: '__custom__' },
])

const isKnownDice = (val?: string) => {
  const target = val || '🎲'
  return DICE_PRESETS.some(d => d.value === target)
}

const getDiceModelValue = (val?: string) => {
  if (!val) return '🎲'
  return isKnownDice(val) ? val : '__custom__'
}

const onDiceSelect = (action: TaskActionItem, val: string | number) => {
  const str = String(val)
  if (str === '__custom__') {
    if (isKnownDice(action.value)) {
      action.value = ''
    }
  } else {
    action.value = str
  }
}

// 插件下拉选项
const getPluginOptions = (actionValue?: string) => {
  const opts = availablePlugins.value.map(p => ({
    label: p.description ? `${p.name} (${p.description})` : p.name,
    value: p.name,
  }))
  if (actionValue && !opts.some(o => o.value === actionValue)) {
    opts.unshift({
      label: `${actionValue} (${t('taskForm.customPlugin')})`,
      value: actionValue,
    })
  }
  opts.push({
    label: `✍️ ${t('taskForm.pluginManualInput')}`,
    value: '__manual__',
  })
  return opts
}

const onPluginSelect = (action: TaskActionItem, val: string | number) => {
  const str = String(val)
  if (str === '__manual__') {
    manualPluginMode.value[action.id] = true
  } else {
    action.value = str
    const info = getPluginInfo(str)
    if (info?.mode) {
      action.mode = info.mode
    }
  }
}

defineProps<{
  actions: TaskActionItem[]
  /** 步骤编号展示：listen 为 04，定时为 03 */
  stepNum: string
  /** 监听后续动作目前由后端白名单执行，不支持自定义插件。 */
  allowCustomPlugin?: boolean
}>()

const emit = defineEmits<{
  (e: 'add'): void
  (e: 'remove', idx: number): void
  (e: 'move', idx: number, delta: number): void
  (e: 'reorder', from: number, to: number): void
}>()
</script>

<template>
  <div class="ui-form-section !bg-[var(--sp-bg-elevated)]">
    <div class="ui-form-step mb-4">
      <span class="ui-form-step-num">{{ stepNum }}</span>
      <h4 class="ui-form-step-title text-violet-600 dark:text-violet-400">{{ t('taskForm.actionSequence') }}</h4>
    </div>
    <div class="space-y-2">
      <div
        v-for="(action, idx) in actions"
        :key="action.id"
        class="border border-gray-100 dark:border-gray-800/60 bg-gray-50/80 dark:bg-white/[0.02] rounded transition-all"
        :class="{
          'opacity-40 border-dashed border-sky-400': draggedIdx === idx,
          'border-sky-500 ring-1 ring-sky-500': dragOverIdx === idx && draggedIdx !== idx
        }"
        @dragover="onDragOver(idx, $event)"
        @dragleave="onDragLeave"
        @drop="onDrop(idx)"
      >
        <div class="flex items-start gap-2 p-2 sm:p-3">
          <!-- 拖拽把手 -->
          <div
            class="shrink-0 pt-2 cursor-grab active:cursor-grabbing text-gray-400 hover:text-sky-500 transition-colors"
            draggable="true"
            title="拖拽以重新排序"
            @dragstart="onDragStart(idx, $event)"
          >
            <GripVertical class="w-4 h-4" />
          </div>

          <!-- 动作类型下拉 -->
          <div class="shrink-0 w-[120px] sm:w-[140px] pt-0.5">
            <CustomSelect
              v-model="action.type"
              :options="[
                { label: t('taskForm.sendText'), value: 'send_text' },
                { label: t('taskForm.clickButton'), value: 'click_text_button' },
                { label: t('taskForm.sendDice'), value: 'send_dice' },
                { label: t('taskForm.botCmd'), value: 'bot_cmd' },
                { label: t('taskForm.delay'), value: 'delay' },
                { label: t('taskForm.aiVision'), value: '_ai_vision', disabled: true },
                { label: t('taskForm.visionSend'), value: 'vision_send', indent: true },
                { label: t('taskForm.visionClick'), value: 'vision_click', indent: true },
                { label: t('taskForm.aiCalc'), value: '_ai_calc', disabled: true },
                { label: t('taskForm.calcSend'), value: 'calc_send', indent: true },
                { label: t('taskForm.calcClick'), value: 'calc_click', indent: true },
                { label: t('taskForm.customPlugin'), value: 'custom_plugin', disabled: allowCustomPlugin === false },
              ]"
              className="w-full"
            />
          </div>

          <!-- 动作具体输入/配置区 -->
          <div class="flex-1 min-w-0">
            <!-- 1. 发送文本 -->
            <input
              v-if="action.type === 'send_text'"
              v-model="action.value"
              :aria-label="t('taskForm.inputText')"
              :placeholder="t('taskForm.textPlaceholder')"
              class="ui-input !h-9 !text-xs !px-2 w-full"
            />

            <!-- 2. 点击按钮 -->
            <div v-else-if="action.type === 'click_text_button'" class="flex flex-col gap-1 w-full">
              <input
                v-model="action.value"
                :aria-label="t('taskForm.buttonText')"
                :placeholder="t('taskForm.buttonPlaceholder')"
                class="ui-input !h-9 !text-xs !px-2 w-full"
              />
              <div class="text-[11px] text-gray-500 dark:text-gray-400 flex items-center gap-1 px-0.5">
                <span class="text-sky-500 shrink-0">💡</span>
                <span>{{ t('taskForm.buttonHint') }}</span>
              </div>
            </div>

            <!-- 3. 发送骰子/表情 -->
            <div v-else-if="action.type === 'send_dice'" class="flex flex-col gap-1 w-full">
              <div class="flex items-center gap-2">
                <div class="w-44 shrink-0">
                  <CustomSelect
                    :model-value="getDiceModelValue(action.value)"
                    :options="diceSelectOptions"
                    @update:model-value="(val) => onDiceSelect(action, val)"
                  />
                </div>
                <input
                  v-if="!isKnownDice(action.value)"
                  v-model="action.value"
                  :aria-label="t('taskForm.inputDice')"
                  :placeholder="t('taskForm.dicePlaceholder')"
                  class="ui-input !h-9 !text-xs !px-2 flex-1"
                />
              </div>
              <div class="text-[11px] text-gray-500 dark:text-gray-400 flex items-center gap-1 px-0.5">
                <span class="text-sky-500 shrink-0">💡</span>
                <span>{{ t('taskForm.sendDiceHint') }}</span>
              </div>
            </div>

            <!-- 4. 延迟 -->
            <input
              v-else-if="action.type === 'delay'"
              v-model="action.value"
              :aria-label="t('taskForm.inputDelay')"
              :placeholder="t('taskForm.delayPlaceholder')"
              class="ui-input !h-9 !text-xs !px-2 w-full"
            />

            <!-- 5. 触发 Bot 命令 -->
            <template v-else-if="action.type === 'bot_cmd'">
              <input
                v-model="action.value"
                :aria-label="t('taskForm.inputBotUsername')"
                :placeholder="t('taskForm.botUsernamePlaceholder')"
                class="ui-input !h-9 !text-xs !px-2 w-full"
              />
              <input
                v-model="action.commandPrefix"
                :aria-label="t('taskForm.inputCommandPrefix')"
                :placeholder="t('taskForm.commandPrefixPlaceholder')"
                class="ui-input !h-9 !text-xs !px-2 mt-1 w-full"
              />
            </template>

            <!-- 6. 自定义插件 -->
            <div v-else-if="action.type === 'custom_plugin'" class="flex flex-col gap-1.5 w-full">
              <div v-if="!manualPluginMode[action.id] && availablePlugins.length > 0" class="w-full">
                <CustomSelect
                  :model-value="action.value"
                  :options="getPluginOptions(action.value)"
                  :placeholder="t('taskForm.pluginSelectPlaceholder')"
                  className="w-full"
                  @update:model-value="(val) => onPluginSelect(action, val)"
                />
              </div>
              <div v-else class="flex items-center gap-2 w-full">
                <input
                  v-model="action.value"
                  :aria-label="t('taskForm.customPlugin')"
                  :placeholder="t('taskForm.customPluginPlaceholder')"
                  class="ui-input !h-9 !text-xs !px-2 flex-1"
                />
                <button
                  v-if="availablePlugins.length > 0"
                  type="button"
                  class="shrink-0 text-[11px] text-sky-600 dark:text-sky-400 hover:underline px-1 py-1"
                  @click="manualPluginMode[action.id] = false"
                >
                  {{ t('taskForm.switchPluginSelect') }}
                </button>
              </div>

              <!-- 插件基本信息提示与在线调试快捷按钮 -->
              <div
                v-if="getPluginInfo(action.value)"
                class="flex items-center justify-between gap-1.5 text-[11px] text-sky-600 dark:text-sky-400 px-0.5"
              >
                <div class="flex items-center gap-1.5 truncate">
                  <span class="font-medium truncate">✧ {{ getPluginInfo(action.value)?.description || action.value }}</span>
                  <span class="shrink-0 text-[10px] px-1 py-0.5 rounded bg-sky-100 dark:bg-sky-950 text-sky-700 dark:text-sky-300 font-mono">
                    {{ getPluginInfo(action.value)?.mode }}
                  </span>
                  <span
                    v-if="getPluginInfo(action.value)?.version"
                    class="shrink-0 text-[10px] px-1 py-0.5 rounded bg-purple-100 dark:bg-purple-950/60 text-purple-700 dark:text-purple-300 font-mono"
                  >
                    v{{ getPluginInfo(action.value)?.version }}
                  </span>
                </div>
                <button
                  type="button"
                  class="shrink-0 text-[11px] text-sky-600 dark:text-sky-400 hover:text-sky-700 dark:hover:text-sky-300 inline-flex items-center gap-1 font-medium px-2 py-0.5 rounded bg-sky-50 dark:bg-sky-950/80 hover:bg-sky-100 dark:hover:bg-sky-900/60 border border-sky-200 dark:border-sky-800/60 transition-colors"
                  :title="t('taskForm.debugPluginTip')"
                  @click="openDebugModalForAction(action)"
                >
                  <Play class="w-2.5 h-2.5 fill-current" />
                  <span>{{ t('taskForm.debugPlugin') }}</span>
                </button>
              </div>

              <!-- 参数配置区域 (若插件声明了 params_schema) -->
              <div
                v-if="getPluginInfo(action.value)?.params_schema?.length"
                class="mt-1 p-2 bg-white/70 dark:bg-black/20 border border-gray-200/80 dark:border-gray-800 rounded flex flex-col gap-2"
              >
                <div class="text-[11px] font-medium text-gray-700 dark:text-gray-300 flex items-center gap-1">
                  <span>⚙️ {{ t('taskForm.pluginParams') }}</span>
                </div>
                <div
                  v-for="field in getPluginInfo(action.value)?.params_schema"
                  :key="field.name"
                  class="flex flex-col gap-0.5 text-xs"
                >
                  <div class="flex items-center justify-between text-[10px] text-gray-500 dark:text-gray-400">
                    <span>{{ field.label || field.name }}</span>
                    <span class="font-mono text-gray-400">{{ field.name }}</span>
                  </div>
                  <!-- 布尔开关 -->
                  <label v-if="field.type === 'bool'" class="inline-flex items-center gap-2 cursor-pointer mt-0.5">
                    <input
                      type="checkbox"
                      :checked="Boolean(getParamValue(action, field.name, field.default))"
                      class="rounded text-sky-600 focus:ring-sky-500 h-3.5 w-3.5"
                      @change="setParamValue(action, field.name, ($event.target as HTMLInputElement).checked)"
                    />
                    <span class="text-[11px] text-gray-600 dark:text-gray-300">
                      {{ getParamValue(action, field.name, field.default) ? t('common.enabled') : t('common.disabled') }}
                    </span>
                  </label>
                  <!-- 整数输入 -->
                  <input
                    v-else-if="field.type === 'int'"
                    type="number"
                    :value="getParamValue(action, field.name, field.default)"
                    :placeholder="field.placeholder || String(field.default ?? '')"
                    class="ui-input !h-8 !text-xs !px-2 w-full"
                    @input="setParamValue(action, field.name, ($event.target as HTMLInputElement).value === '' ? undefined : Number(($event.target as HTMLInputElement).value))"
                  />
                  <!-- 字符串输入 -->
                  <input
                    v-else
                    type="text"
                    :value="String(getParamValue(action, field.name, field.default) ?? '')"
                    :placeholder="field.placeholder || String(field.default ?? '')"
                    class="ui-input !h-8 !text-xs !px-2 w-full"
                    @input="setParamValue(action, field.name, ($event.target as HTMLInputElement).value)"
                  />
                </div>
              </div>

              <!-- 插件超时设置 -->
              <div v-if="getPluginInfo(action.value)" class="flex items-center gap-2 text-xs pt-1">
                <span class="text-[11px] text-gray-500 dark:text-gray-400 whitespace-nowrap">{{ t('taskForm.pluginTimeout') }}:</span>
                <input
                  type="number"
                  min="1"
                  max="300"
                  :value="action.timeout ?? ''"
                  :placeholder="t('taskForm.pluginTimeoutPlaceholder')"
                  class="ui-input !h-7 !w-28 !text-xs !px-2"
                  @input="action.timeout = ($event.target as HTMLInputElement).value ? Math.min(Number(($event.target as HTMLInputElement).value), 300) : undefined"
                />
              </div>
            </div>

            <!-- 7. AI 识图 / AI 计算 动作 -->
            <div
              v-else-if="['vision_send', 'vision_click', 'calc_send', 'calc_click'].includes(action.type)"
              class="flex flex-col gap-1 w-full"
            >
              <input
                v-model="action.aiPrompt"
                :aria-label="t('taskForm.inputAiPrompt')"
                :placeholder="t('taskForm.aiPromptPlaceholder')"
                class="ui-input !h-9 !text-xs !px-2 w-full"
              />
              <div class="text-[11px] text-gray-500 dark:text-gray-400 flex items-center gap-1 px-0.5">
                <span class="text-sky-500 shrink-0">💡</span>
                <span v-if="action.type === 'vision_send'">{{ t('taskForm.visionSendHint') }}</span>
                <span v-else-if="action.type === 'vision_click'">{{ t('taskForm.visionClickHint') }}</span>
                <span v-else-if="action.type === 'calc_send'">{{ t('taskForm.calcSendHint') }}</span>
                <span v-else-if="action.type === 'calc_click'">{{ t('taskForm.calcClickHint') }}</span>
              </div>
            </div>

            <span v-else class="h-9 flex items-center text-xs text-gray-400 px-2">-</span>
          </div>

          <!-- 操作按钮：高级设置/上移/下移/删除 -->
          <div class="flex items-center gap-0.5 shrink-0 pt-0.5">
            <button
              v-if="action.type !== 'delay'"
              type="button"
              class="p-1.5 text-gray-400 hover:text-sky-600 dark:hover:text-sky-400 hover:bg-sky-50 dark:hover:bg-sky-950/30 rounded-sm transition-colors"
              :class="{ '!text-sky-600 dark:!text-sky-400 bg-sky-50/80 dark:bg-sky-950/40': expandedAdvanced[action.id] || action.continue_on_error || action.skip_if_matched }"
              :title="expandedAdvanced[action.id] ? t('taskForm.collapseOptions') : t('taskForm.advancedActionOptions')"
              @click="toggleAdvanced(action.id)"
            >
              <SlidersHorizontal class="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              class="p-1.5 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-white/[0.05] rounded-sm transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              :aria-label="t('taskForm.moveUp')"
              :title="t('taskForm.moveUp')"
              :disabled="idx === 0"
              @click="emit('move', idx, -1)"
            >
              <ArrowUp class="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              class="p-1.5 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-white/[0.05] rounded-sm transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              :aria-label="t('taskForm.moveDown')"
              :title="t('taskForm.moveDown')"
              :disabled="idx === actions.length - 1"
              @click="emit('move', idx, 1)"
            >
              <ArrowDown class="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              class="p-1.5 text-gray-400 hover:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-500/10 rounded-sm transition-colors"
              :aria-label="t('taskForm.removeAction')"
              :title="t('taskForm.removeAction')"
              @click="emit('remove', idx)"
            >
              <Trash2 class="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <!-- 高级管道配置抽屉：容错继续、条件跳过与宏变量 -->
        <div
          v-if="expandedAdvanced[action.id] && action.type !== 'delay'"
          class="border-t border-gray-100 dark:border-gray-800/80 p-2.5 sm:px-3 sm:py-2.5 bg-white/60 dark:bg-black/20 flex flex-col gap-2 text-xs"
        >
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <!-- 容错继续开关 -->
            <label class="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                v-model="action.continue_on_error"
                class="rounded text-sky-600 focus:ring-sky-500 h-3.5 w-3.5 mt-0.5"
              />
              <div class="flex flex-col">
                <span class="font-medium text-gray-700 dark:text-gray-200">{{ t('taskForm.continueOnError') }}</span>
                <span class="text-[11px] text-gray-400 leading-snug">{{ t('taskForm.continueOnErrorDesc') }}</span>
              </div>
            </label>

            <!-- 条件跳过输入 -->
            <div class="flex flex-col gap-1">
              <span class="font-medium text-gray-700 dark:text-gray-200">{{ t('taskForm.skipIfMatched') }}</span>
              <input
                v-model="action.skip_if_matched"
                :placeholder="t('taskForm.skipIfMatchedPlaceholder')"
                class="ui-input !h-7 !text-xs !px-2 w-full"
              />
              <span class="text-[10px] text-gray-400">{{ t('taskForm.skipIfMatchedDesc') }}</span>
            </div>
          </div>

          <!-- 宏变量快速填入 -->
          <div class="flex flex-wrap items-center gap-1.5 pt-1 border-t border-gray-100 dark:border-gray-800/50">
            <span class="text-[11px] text-gray-400 flex items-center gap-1">
              <Sparkles class="w-3 h-3 text-amber-500" />
              {{ t('taskForm.macroHelper') }}:
            </span>
            <button
              v-for="m in MACRO_PRESETS"
              :key="m.label"
              type="button"
              class="px-1.5 py-0.5 text-[10px] font-mono bg-sky-50 dark:bg-sky-950/40 text-sky-700 dark:text-sky-300 border border-sky-200/60 dark:border-sky-800/40 rounded hover:bg-sky-100 transition-colors"
              :title="m.desc"
              @click="insertMacro(action, m.label)"
            >
              {{ m.label }}
            </button>
          </div>
        </div>
      </div>

      <!-- 添加动作按钮 -->
      <button
        type="button"
        class="flex items-center gap-1.5 px-3 py-2.5 text-xs text-gray-500 hover:text-sky-600 dark:hover:text-sky-400 border border-dashed border-gray-300 dark:border-gray-700 hover:border-sky-400/60 dark:hover:border-sky-500/40 hover:bg-sky-50/50 dark:hover:bg-sky-500/5 transition-colors w-full justify-center"
        @click="emit('add')"
      >
        <Plus class="w-3.5 h-3.5" /> {{ t('taskForm.addAction') }}
      </button>
    </div>
  </div>

  <!-- 动作内联插件调试弹窗 -->
  <Modal
    :title="`${t('taskForm.debugPlugin')}: ${debugAction?.value ?? ''}`"
    :is-open="isActionDebugModalOpen"
    max-width-class="max-w-xl"
    z-index-class="z-[110]"
    @close="isActionDebugModalOpen = false"
  >
    <div v-if="debugAction" class="space-y-4 text-xs">
      <div class="flex items-center justify-between gap-2 text-gray-500 dark:text-gray-400 text-[11px]">
        <span class="truncate">{{ debugPluginInfo?.description || debugAction.value }}</span>
        <span class="shrink-0 font-mono px-1.5 py-0.5 rounded text-[10px] bg-sky-100 dark:bg-sky-950 text-sky-700 dark:text-sky-300">
          {{ debugPluginInfo?.mode || 'reactive' }}
        </span>
      </div>

      <!-- 模式提示 -->
      <div
        class="p-2.5 rounded border text-[11px] leading-relaxed"
        :class="debugPluginInfo?.mode === 'active' ? 'border-emerald-200/70 bg-emerald-50/40 dark:border-emerald-900/50 dark:bg-emerald-950/20 text-emerald-800 dark:text-emerald-300' : 'border-sky-200/70 bg-sky-50/40 dark:border-sky-900/50 dark:bg-sky-950/20 text-sky-800 dark:text-sky-300'"
      >
        {{ debugPluginInfo?.mode === 'active' ? t('settings.pluginsPlaygroundModeActiveTip') : t('settings.pluginsPlaygroundModeReactiveTip') }}
      </div>

      <!-- 模拟触发消息 (仅 reactive 或提供时输入) -->
      <div v-if="debugPluginInfo?.mode !== 'active'" class="space-y-1">
        <label class="font-medium text-gray-700 dark:text-gray-300">
          {{ t('settings.pluginsTestInputLabel') }}
        </label>
        <textarea
          v-model="debugInputText"
          rows="2"
          class="ui-input !h-auto !py-1.5 !px-2.5 !text-xs w-full font-mono"
          :placeholder="t('settings.pluginsTestInputPlaceholder')"
        />
      </div>

      <!-- 参数调试配置 -->
      <div v-if="debugPluginInfo?.params_schema && debugPluginInfo.params_schema.length" class="p-3 bg-gray-50/80 dark:bg-white/[0.02] border border-gray-200 dark:border-gray-800 rounded space-y-2">
        <div class="font-medium text-[11px] text-gray-700 dark:text-gray-300">
          {{ t('settings.pluginsTestParamsLabel') }}
        </div>
        <div
          v-for="field in debugPluginInfo.params_schema"
          :key="field.name"
          class="flex flex-col gap-1"
        >
          <div class="flex justify-between text-[10px] text-gray-500">
            <span>{{ field.label || field.name }}</span>
            <span class="font-mono text-gray-400">{{ field.name }}</span>
          </div>
          <label v-if="field.type === 'bool'" class="inline-flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"              :checked="Boolean(debugParams[field.name])"              class="rounded text-sky-600 focus:ring-sky-500 h-3.5 w-3.5"              @change="debugParams[field.name] = ($event.target as HTMLInputElement).checked"            />
            <span class="text-[11px] text-gray-600 dark:text-gray-300">
              {{ debugParams[field.name] ? t('common.enabled') : t('common.disabled') }}
            </span>
          </label>
          <input
            v-else-if="field.type === 'int'"
            type="number"
            :value="debugParams[field.name]"
            :placeholder="field.placeholder || String(field.default ?? '')"
            class="ui-input !h-8 !text-xs !px-2 w-full"
            @input="debugParams[field.name] = ($event.target as HTMLInputElement).value === '' ? undefined : Number(($event.target as HTMLInputElement).value)"
          />
          <input
            v-else
            type="text"
            :value="String(debugParams[field.name] ?? '')"
            :placeholder="field.placeholder || String(field.default ?? '')"
            class="ui-input !h-8 !text-xs !px-2 w-full"
            @input="debugParams[field.name] = ($event.target as HTMLInputElement).value"
          />
        </div>
      </div>

      <div class="flex items-center justify-between gap-2 pt-1">
        <button
          type="button"
          class="ui-btn-secondary !py-1 !px-2.5 !text-xs"
          @click="applyDebugParamsToAction"
        >
          {{ t('common.save') }}
        </button>

        <button
          type="button"
          class="ui-btn-primary !px-4 !py-1.5 !text-xs inline-flex items-center gap-1.5"
          :disabled="debugRunning"
          @click="runActionPluginTest"
        >
          <RefreshCw v-if="debugRunning" class="w-3.5 h-3.5 animate-spin" />
          <Play v-else class="w-3.5 h-3.5 fill-current" />
          {{ debugRunning ? t('settings.pluginsTestRunning') : t('settings.pluginsRunTest') }}
        </button>
      </div>

      <!-- 调试结果回显 -->
      <div v-if="debugResult" class="p-3 border rounded space-y-2 transition-all" :class="debugResult.success && debugResult.handled ? 'border-emerald-500/50 bg-emerald-50/20 dark:bg-emerald-950/20' : (debugResult.error ? 'border-red-500/50 bg-red-50/20 dark:bg-red-950/20' : 'border-amber-500/50 bg-amber-50/20 dark:bg-amber-950/20')">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-1.5 font-medium">
            <CheckCircle2 v-if="debugResult.success && debugResult.handled" class="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <AlertCircle v-else class="w-4 h-4 text-amber-600 dark:text-amber-400" />
            <span>{{ debugResult.handled ? t('settings.pluginsHandledTrue') : (debugResult.error ? t('settings.pluginsHandledError') : t('settings.pluginsHandledFalse')) }}</span>
          </div>
          <div class="flex items-center gap-1 text-[11px] text-gray-500 font-mono">
            <Clock class="w-3 h-3" />
            <span>{{ debugResult.duration_ms }} ms</span>
          </div>
        </div>

        <div v-if="debugResult.reply_text" class="p-2 bg-white/80 dark:bg-black/30 rounded border border-gray-200 dark:border-gray-800">
          <span class="text-[10px] text-gray-400 block mb-0.5">{{ t('settings.pluginsReplyOutput') }}</span>
          <div class="font-mono text-xs text-sky-600 dark:text-sky-300 font-semibold select-all">
            {{ debugResult.reply_text }}
          </div>
        </div>

        <div v-if="debugResult.logs && debugResult.logs.length" class="space-y-1">
          <span class="text-[10px] text-gray-400 block">{{ t('settings.pluginsLogsLabel') }}</span>
          <div class="p-2 bg-gray-900 text-gray-200 rounded font-mono text-[11px] max-h-28 overflow-y-auto space-y-0.5 select-all">
            <div v-for="(log, idx) in debugResult.logs" :key="idx">{{ log }}</div>
          </div>
        </div>
      </div>
    </div>
  </Modal>
</template>

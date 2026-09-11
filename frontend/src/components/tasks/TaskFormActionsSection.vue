<script setup lang="ts">
/**
 * 任务表单：动作序列编辑区块。
 */
import { ref, onMounted } from 'vue'
import { Plus, Trash2, ArrowUp, ArrowDown } from 'lucide-vue-next'
import CustomSelect from '../CustomSelect.vue'
import type { TaskActionItem } from '../../lib/types'
import { useI18n } from '../../composables/useI18n'
import { getPlugins, type PluginInfo } from '../../lib/api'
import { withToken } from '../../lib/api/core'

const { t } = useI18n()

const availablePlugins = ref<PluginInfo[]>([])

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
        class="flex items-center gap-2 p-2 sm:p-3 border border-gray-100 dark:border-gray-800/60 bg-gray-50/80 dark:bg-white/[0.02]"
      >
        <div class="shrink-0 w-[120px] sm:w-[140px]">
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
        <div class="flex-1 min-w-0">
          <input
            v-if="action.type === 'send_text' || action.type === 'click_text_button'"
            v-model="action.value"
            :aria-label="t('taskForm.inputText')"
            :placeholder="t('taskForm.textPlaceholder')"
            class="ui-input !h-9 !text-xs !px-2"
          />
          <input
            v-else-if="action.type === 'delay'"
            v-model="action.value"
            :aria-label="t('taskForm.inputDelay')"
            :placeholder="t('taskForm.delayPlaceholder')"
            class="ui-input !h-9 !text-xs !px-2"
          />
          <input
            v-else-if="action.type === 'send_dice'"
            v-model="action.value"
            :aria-label="t('taskForm.inputDice')"
            placeholder="🎲"
            class="ui-input !h-9 !text-xs !px-2"
          />
          <template v-else-if="action.type === 'bot_cmd'">
            <input
              v-model="action.value"
              :aria-label="t('taskForm.inputBotUsername')"
              :placeholder="t('taskForm.botUsernamePlaceholder')"
              class="ui-input !h-9 !text-xs !px-2"
            />
            <input
              v-model="action.commandPrefix"
              :aria-label="t('taskForm.inputCommandPrefix')"
              :placeholder="t('taskForm.commandPrefixPlaceholder')"
              class="ui-input !h-9 !text-xs !px-2 mt-1"
            />
          </template>
          <div v-else-if="action.type === 'custom_plugin'" class="flex flex-col gap-1.5 w-full">
            <input
              v-model="action.value"
              list="task-form-custom-plugins-list"
              :aria-label="t('taskForm.customPlugin')"
              :placeholder="t('taskForm.customPluginPlaceholder')"
              class="ui-input !h-9 !text-xs !px-2 w-full"
            />
            <div
              v-if="getPluginInfo(action.value)"
              class="flex items-center gap-1.5 text-[11px] text-sky-600 dark:text-sky-400 px-0.5 truncate"
            >
              <span class="font-medium truncate">✦ {{ getPluginInfo(action.value)?.description || action.value }}</span>
              <span class="shrink-0 text-[10px] px-1 py-0.5 rounded bg-sky-100 dark:bg-sky-950 text-sky-700 dark:text-sky-300 font-mono">
                {{ getPluginInfo(action.value)?.mode }}
              </span>
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
                  @input="setParamValue(action, field.name, Number(($event.target as HTMLInputElement).value))"
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
          </div>
          <input
            v-else-if="['vision_send', 'vision_click', 'calc_send', 'calc_click'].includes(action.type)"
            v-model="action.aiPrompt"
            :aria-label="t('taskForm.inputAiPrompt')"
            :placeholder="t('taskForm.aiPromptPlaceholder')"
            class="ui-input !h-9 !text-xs !px-2"
          />
          <span v-else class="h-9 flex items-center text-xs text-gray-400 px-2">-</span>
        </div>
        <div class="flex items-center gap-0.5 shrink-0">
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
      <datalist id="task-form-custom-plugins-list">
        <option
          v-for="p in availablePlugins"
          :key="p.name"
          :value="p.name"
        >
          {{ p.description ? `${p.description} (${p.mode})` : p.mode }}
        </option>
      </datalist>
      <button
        type="button"
        class="flex items-center gap-1.5 px-3 py-2.5 text-xs text-gray-500 hover:text-sky-600 dark:hover:text-sky-400 border border-dashed border-gray-300 dark:border-gray-700 hover:border-sky-400/60 dark:hover:border-sky-500/40 hover:bg-sky-50/50 dark:hover:bg-sky-500/5 transition-colors w-full justify-center"
        @click="emit('add')"
      >
        <Plus class="w-3.5 h-3.5" /> {{ t('taskForm.addAction') }}
      </button>
    </div>
  </div>
</template>

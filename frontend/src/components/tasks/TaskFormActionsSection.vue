<script setup lang="ts">
/**
 * 任务表单：动作序列编辑区块。
 */
import { Plus, Trash2, ArrowUp, ArrowDown } from 'lucide-vue-next'
import CustomSelect from '../CustomSelect.vue'
import type { TaskActionItem } from '../../lib/types'
import { useI18n } from '../../composables/useI18n'

const { t } = useI18n()

defineProps<{
  actions: TaskActionItem[]
  /** 步骤编号展示：listen 为 04，定时为 03 */
  stepNum: string
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
              { label: t('taskForm.aiVision'), value: '_ai_vision', disabled: true },
              { label: t('taskForm.visionSend'), value: 'vision_send', indent: true },
              { label: t('taskForm.visionClick'), value: 'vision_click', indent: true },
              { label: t('taskForm.aiCalc'), value: '_ai_calc', disabled: true },
              { label: t('taskForm.calcSend'), value: 'calc_send', indent: true },
              { label: t('taskForm.calcClick'), value: 'calc_click', indent: true },
              { label: t('taskForm.delay'), value: 'delay' },
            ]"
            className="w-full"
          />
        </div>
        <div class="flex-1 min-w-0">
          <input
            v-if="action.type === 'send_text' || action.type === 'click_text_button'"
            v-model="action.value"
            :placeholder="t('taskForm.textPlaceholder')"
            class="ui-input !h-9 !text-xs !px-2"
          />
          <input
            v-else-if="action.type === 'delay'"
            v-model="action.value"
            :placeholder="t('taskForm.delayPlaceholder')"
            class="ui-input !h-9 !text-xs !px-2"
          />
          <input
            v-else-if="action.type === 'send_dice'"
            v-model="action.value"
            placeholder="🎲"
            class="ui-input !h-9 !text-xs !px-2"
          />
          <template v-else-if="action.type === 'bot_cmd'">
            <input
              v-model="action.value"
              :placeholder="t('taskForm.botUsernamePlaceholder')"
              class="ui-input !h-9 !text-xs !px-2"
            />
            <input
              v-model="action.commandPrefix"
              :placeholder="t('taskForm.commandPrefixPlaceholder')"
              class="ui-input !h-9 !text-xs !px-2 mt-1"
            />
          </template>
          <input
            v-else-if="['vision_send', 'vision_click', 'calc_send', 'calc_click'].includes(action.type)"
            v-model="action.aiPrompt"
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

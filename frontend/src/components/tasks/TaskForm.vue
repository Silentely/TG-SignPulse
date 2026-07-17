<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { Plus, Trash2, ArrowUp, ArrowDown, RefreshCw } from 'lucide-vue-next'
import { listAccounts, getAccountChats, searchAccountChats } from '../../lib/api'
import type { SignTask, AccountInfo, ChatInfo, CreateSignTaskRequest, UpdateSignTaskRequest } from '../../lib/api'
import CustomSelect from '../CustomSelect.vue'
import MultiSelect from '../MultiSelect.vue'
import { useI18n } from '../../composables/useI18n'
import { useToast } from '../../composables/useToast'
import { useAuthStore } from '../../stores/auth'
import type { TaskActionItem, RawTaskAction, BuiltAction } from '../../lib/types'
import { getLocalizedErrorMessage } from '../../lib/types'
import { parseActions as parseActionsUtil, nextActionId, buildActions, debounce } from '../../lib/task-form-utils'
import { devLog } from '../../lib/devLog'

const { t } = useI18n()
const toast = useToast()
const authStore = useAuthStore()

const props = defineProps<{ initialTask?: SignTask }>()
const emit = defineEmits<{ (e: 'update:payload', value: CreateSignTaskRequest | UpdateSignTaskRequest): void }>()
const accounts = ref<AccountInfo[]>([])
const selectedAccounts = ref<string[]>([])
const allAccountsMode = ref(false)
const accountOptions = computed(() => accounts.value.map(a => ({ label: a.name, value: a.name })))
const scheduleMode = ref<'scheduled' | 'listen'>('scheduled')
const timeRange = ref('08:00-19:00')
const taskName = ref('')
const retryCount = ref(3)
const availableChats = ref<ChatInfo[]>([])
const chatSearch = ref('')
const chatSearchResults = ref<ChatInfo[]>([])
const chatSearchLoading = ref(false)
const chatListRefreshing = ref(false)
const chatListError = ref('')
/** 多目标聊天（共享动作序列；build 时复制到每个 chat） */
type TargetChatDraft = {
  id: number
  chatId: number
  chatName: string
  messageThreadId: string
  senderFilter: string
  sourceAccount: string
}
let _chatDraftId = 0
const nextChatDraftId = () => ++_chatDraftId
const targetChats = ref<TargetChatDraft[]>([
  { id: nextChatDraftId(), chatId: 0, chatName: '', messageThreadId: '', senderFilter: '', sourceAccount: '' },
])
const activeChatIndex = ref(0)
const activeChat = computed(() => targetChats.value[activeChatIndex.value] || targetChats.value[0])
const selectedChatId = computed({
  get: () => activeChat.value?.chatId ?? 0,
  set: (v: number) => { if (activeChat.value) activeChat.value.chatId = v },
})
const selectedChatName = computed({
  get: () => activeChat.value?.chatName ?? '',
  set: (v: string) => { if (activeChat.value) activeChat.value.chatName = v },
})
const messageThreadId = computed({
  get: () => activeChat.value?.messageThreadId ?? '',
  set: (v: string) => { if (activeChat.value) activeChat.value.messageThreadId = v },
})
const senderFilter = computed({
  get: () => activeChat.value?.senderFilter ?? '',
  set: (v: string) => { if (activeChat.value) activeChat.value.senderFilter = v },
})
const selectedAccount = computed({
  get: () => activeChat.value?.sourceAccount || selectedAccounts.value[0] || '',
  set: (v: string) => { if (activeChat.value) activeChat.value.sourceAccount = v },
})
const listenerKeywords = ref('')
const listenerMatchMode = ref('contains')
const listenerPushChannel = ref('continue')
const listenerForwardChatId = ref('')
const listenerForwardThreadId = ref('')
const listenerBarkUrl = ref('')
const listenerCustomUrl = ref('')
const actions = ref<TaskActionItem[]>([{ id: nextActionId(), type: 'send_text', value: '', aiPrompt: '' }])

const loadAccounts = async () => {
  try {
    const token = authStore.token || ''
    const res = await listAccounts(token)
    accounts.value = res.accounts || []
    if (props.initialTask) {
      taskName.value = props.initialTask.name || ''
      retryCount.value = props.initialTask.retry_count ?? 3
      scheduleMode.value = props.initialTask.execution_mode === 'listen' ? 'listen' : 'scheduled'
      if (props.initialTask.execution_mode === 'range') timeRange.value = props.initialTask.range_start + '-' + props.initialTask.range_end
      else timeRange.value = props.initialTask.sign_at || '08:00-19:00'
      const taskAccs = props.initialTask.account_names?.length ? props.initialTask.account_names : [props.initialTask.account_name]
      if (taskAccs.includes('*')) {
        allAccountsMode.value = true
        selectedAccounts.value = accounts.value.map(a => a.name)
      } else {
        allAccountsMode.value = false
        selectedAccounts.value = taskAccs.filter((a: string) => accounts.value.some(acc => acc.name === a))
      }
      if (props.initialTask.chats?.length > 0) {
        targetChats.value = props.initialTask.chats.map((chat) => ({
          id: nextChatDraftId(),
          chatId: Number(chat.chat_id) || 0,
          chatName: chat.name || '',
          messageThreadId: chat.message_thread_id ? String(chat.message_thread_id) : '',
          senderFilter: chat.sender_filter || '',
          sourceAccount: chat.source_account || selectedAccounts.value[0] || accounts.value[0]?.name || '',
        }))
        activeChatIndex.value = 0
        const primary = props.initialTask.chats[0]
        const la = primary.actions?.find((a: RawTaskAction) => a.action === 8)
        if (la) {
          listenerKeywords.value = Array.isArray(la.keywords) ? la.keywords.join('\n') : ''
          listenerMatchMode.value = la.match_mode || 'contains'
          listenerPushChannel.value = la.push_channel || 'continue'
          listenerForwardChatId.value = la.forward_chat_id ? String(la.forward_chat_id) : ''
          listenerForwardThreadId.value = la.forward_message_thread_id ? String(la.forward_message_thread_id) : ''
          listenerBarkUrl.value = la.bark_url || ''
          listenerCustomUrl.value = la.custom_url || ''
          if (la.continue_actions) parseActions(la.continue_actions)
        } else if (primary.actions) parseActions(primary.actions)
      } else if (selectedAccounts.value[0] || accounts.value[0]?.name) {
        targetChats.value[0].sourceAccount = selectedAccounts.value[0] || accounts.value[0]?.name || ''
      }
    } else {
      if (accounts.value.length > 0) {
        allAccountsMode.value = true
        selectedAccounts.value = accounts.value.map(a => a.name)
        targetChats.value[0].sourceAccount = selectedAccounts.value[0] || ''
      }
    }
    if (selectedAccount.value) loadChats(selectedAccount.value)
  } catch (e: unknown) {
    devLog.error(getLocalizedErrorMessage(e, t))
    toast.error(getLocalizedErrorMessage(e, t, t('taskForm.loadAccountsFailed')))
  }
}
const parseActions = (raw: RawTaskAction[]) => {
  const parsed = parseActionsUtil(raw)
  if (parsed.length > 0) actions.value = parsed
}
let loadChatsAbort: AbortController | null = null
const loadChats = async (n: string, forceRefresh: boolean = false) => {
  // Cancel previous request to avoid race conditions
  if (loadChatsAbort) { loadChatsAbort.abort(); loadChatsAbort = null }
  const controller = new AbortController()
  loadChatsAbort = controller
  chatListRefreshing.value = true
  chatListError.value = ''
  const token = authStore.token||''
  try {
    const result = await getAccountChats(token, n, forceRefresh)
    if (controller.signal.aborted) return
    availableChats.value = result || []
  } catch (e: unknown) {
    if (controller.signal.aborted) return
    const msg = getLocalizedErrorMessage(e, t)
    if (msg.includes('登录已失效') || msg.includes('session') || msg.includes('Session')) {
      chatListError.value = t('taskForm.sessionInvalid')
    } else {
      chatListError.value = t('taskForm.loadFailed')
    }
    availableChats.value = []
    if (forceRefresh) {
      toast.error(getLocalizedErrorMessage(e, t, t('taskForm.loadChatsFailed')))
    }
  } finally {
    if (loadChatsAbort === controller) { loadChatsAbort = null; chatListRefreshing.value = false }
  }
}
const refreshChats = async () => { if (!selectedAccount.value || chatListRefreshing.value) return; await loadChats(selectedAccount.value, true) }
watch(selectedAccounts,(v)=>{if(v.length>0&&!v.includes(selectedAccount.value))selectedAccount.value=v[0];else if(v.length===0){selectedAccount.value='';availableChats.value=[]}})
watch(selectedAccount, async (v)=>{
  availableChats.value=[]
  if(v) {
    await loadChats(v, false)
    // If cache was empty and account didn't change, try force refresh
    if (availableChats.value.length === 0 && v === selectedAccount.value) {
      await loadChats(v, true)
    }
  } else {
    chatListRefreshing.value = false
  }
})
let st: ReturnType<typeof setTimeout> | null = null
watch(chatSearch,(v)=>{if(!v.trim()){chatSearchResults.value=[];return};if(st)clearTimeout(st);st=setTimeout(async()=>{chatSearchLoading.value=true;try{const t=authStore.token||'';const r=await searchAccountChats(t,selectedAccount.value,v.trim());chatSearchResults.value=r.items||[]}catch(e){devLog.error('chat search failed', e)}finally{chatSearchLoading.value=false}},300)})
const selectChat=(c: ChatInfo)=>{selectedChatId.value=c.id;selectedChatName.value=c.title||c.username||String(c.id);chatSearch.value='';chatSearchResults.value=[]}
const addTargetChat = () => {
  targetChats.value.push({
    id: nextChatDraftId(),
    chatId: 0,
    chatName: '',
    messageThreadId: '',
    senderFilter: '',
    sourceAccount: selectedAccounts.value[0] || '',
  })
  activeChatIndex.value = targetChats.value.length - 1
}
const removeTargetChat = (idx: number) => {
  if (targetChats.value.length <= 1) return
  targetChats.value.splice(idx, 1)
  if (activeChatIndex.value >= targetChats.value.length) {
    activeChatIndex.value = targetChats.value.length - 1
  }
}
const addAction=()=>actions.value.push({id:nextActionId(),type:'send_text',value:'',aiPrompt:''})
const removeAction=(i:number)=>actions.value.splice(i,1)
const moveAction=(i:number,d:number)=>{if(i+d<0||i+d>=actions.value.length)return;const t=actions.value[i];actions.value[i]=actions.value[i+d];actions.value[i+d]=t}
const buildPayload = () => {
  let em: 'fixed' | 'range' | 'listen' = 'fixed'
  let sa = '08:00', rs = '', re = ''
  if (scheduleMode.value === 'listen') {
    em = 'listen'
  } else {
    const p = timeRange.value.split('-')
    if (p.length === 2) { em = 'range'; rs = p[0].trim(); re = p[1].trim(); sa = rs }
    else sa = timeRange.value.trim() || '08:00'
  }

  const ba = buildActions(actions.value)

  let ca = ba
  if (scheduleMode.value === 'listen') {
    const kw = listenerKeywords.value.split('\n').map((k: string) => k.trim()).filter(Boolean)
    const la: BuiltAction = { action: 8, keywords: kw, match_mode: listenerMatchMode.value, push_channel: listenerPushChannel.value }
    if (listenerPushChannel.value === 'forward') {
      if (listenerForwardChatId.value) la.forward_chat_id = listenerForwardChatId.value
      if (listenerForwardThreadId.value) la.forward_message_thread_id = listenerForwardThreadId.value
    }
    if (listenerPushChannel.value === 'bark' && listenerBarkUrl.value) la.bark_url = listenerBarkUrl.value
    if (listenerPushChannel.value === 'custom' && listenerCustomUrl.value) la.custom_url = listenerCustomUrl.value
    if (listenerPushChannel.value === 'continue' && ba.length > 0) la.continue_actions = ba
    ca = [la]
  }

  const chats = targetChats.value
    .filter((c) => c.chatId)
    .map((c) => ({
      chat_id: c.chatId,
      name: c.chatName,
      actions: ca as import('../../lib/types').RawTaskAction[],
      action_interval: 1,
      message_thread_id: c.messageThreadId ? Number(c.messageThreadId) : undefined,
      sender_filter: c.senderFilter.trim() || undefined,
      source_account: c.sourceAccount || undefined,
    }))

  // 至少一个 chat 占位，避免空配置无法保存
  const safeChats = chats.length
    ? chats
    : [{
        chat_id: selectedChatId.value || 0,
        name: selectedChatName.value || '',
        actions: ca as import('../../lib/types').RawTaskAction[],
        action_interval: 1,
        message_thread_id: messageThreadId.value ? Number(messageThreadId.value) : undefined,
        sender_filter: senderFilter.value.trim() || undefined,
        source_account: selectedAccount.value || undefined,
      }]

  const primaryName = safeChats[0]?.name || selectedChatName.value
  return {
    name: taskName.value || primaryName || `task_${Date.now()}`,
    account_name: selectedAccounts.value[0] || '',
    account_names: allAccountsMode.value ? ['*'] : selectedAccounts.value,
    sign_at: sa, execution_mode: em, range_start: rs, range_end: re, random_seconds: 0,
    retry_count: retryCount.value,
    chats: safeChats,
  }
}
const debouncedEmit = debounce(() => { emit('update:payload', buildPayload()) }, 300)
/** 同步刷新 payload（保存前调用，确保拿到最新值） */
const flushPayload = () => { emit('update:payload', buildPayload()) }
defineExpose({ flushPayload })
watch([taskName,selectedAccounts,allAccountsMode,scheduleMode,timeRange,targetChats,activeChatIndex,actions,retryCount,listenerKeywords,listenerMatchMode,listenerPushChannel,listenerForwardChatId,listenerForwardThreadId,listenerBarkUrl,listenerCustomUrl], () => { debouncedEmit() }, {deep:true})
onMounted(()=>{loadAccounts()})
</script>
<template>
  <div class="space-y-6 text-left">
    <!-- 01 基础信息 -->
    <div class="ui-form-section">
      <div class="ui-form-step mb-4">
        <span class="ui-form-step-num">01</span>
        <h4 class="ui-form-step-title">{{ t('taskForm.taskName') }} / {{ t('taskForm.linkedAccounts') }}</h4>
      </div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
      <div class="space-y-1.5">
        <label class="ui-label-strong">{{ t('taskForm.taskName') }}</label>
        <input v-model="taskName" :placeholder="t('taskForm.taskNamePlaceholder')" :disabled="!!props.initialTask" class="ui-input disabled:opacity-50" />
      </div>
      <div class="space-y-1.5">
        <label class="ui-label-strong">{{ t('taskForm.linkedAccounts') }}</label>
        <MultiSelect v-model="selectedAccounts" :options="accountOptions" :placeholder="t('taskForm.linkedAccountsPlaceholder')" :allMode="allAccountsMode" @update:allMode="allAccountsMode = $event" />
      </div>
      <div class="space-y-1.5">
        <label class="ui-label-strong">{{ t('taskForm.scheduleMode') }}</label>
        <CustomSelect v-model="scheduleMode" :options="[{label: t('taskForm.scheduled'), value:'scheduled'}, {label: t('taskForm.listen'), value:'listen'}]" />
      </div>
      <div class="space-y-1.5">
        <label class="ui-label-strong">{{ t('taskForm.timeRange') }}</label>
        <input v-model="timeRange" :disabled="scheduleMode === 'listen'" :placeholder="scheduleMode === 'listen' ? '24H' : t('taskForm.timeRangePlaceholder')" class="ui-input disabled:opacity-50 disabled:bg-gray-50 dark:disabled:bg-gray-950" />
      </div>
      <div class="space-y-1.5">
        <label class="ui-label-strong">{{ t('taskForm.retryCount') }}</label>
        <input v-model.number="retryCount" type="number" min="0" max="99" class="ui-input" />
      </div>
    </div>
    </div>
    <!-- 02 目标会话 -->
    <div class="ui-form-section ui-form-section-accent">
      <div class="mb-4 flex items-center justify-between gap-2">
        <div class="ui-form-step">
          <span class="ui-form-step-num">02</span>
          <h4 class="ui-form-step-title text-sky-600 dark:text-sky-400">{{ t('taskForm.targetChat') }}</h4>
        </div>
        <button type="button" class="text-[11px] text-sky-600 dark:text-sky-400 hover:underline font-medium" @click="addTargetChat">+ {{ t('taskForm.addTargetChat') }}</button>
      </div>
      <div v-if="targetChats.length > 1" class="flex flex-wrap gap-2 mb-4">
        <button
          v-for="(chat, idx) in targetChats"
          :key="chat.id"
          type="button"
          @click="activeChatIndex = idx"
          class="px-2.5 py-1 text-[11px] border transition-colors max-w-[12rem] truncate"
          :class="activeChatIndex === idx
            ? 'border-sky-400 bg-sky-50 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300'
            : 'border-gray-200 dark:border-gray-700 text-gray-500 hover:border-gray-300 dark:hover:border-gray-600'"
        >
          {{ chat.chatName || chat.chatId || `${t('taskForm.targetChat')} ${idx + 1}` }}
          <span
            v-if="targetChats.length > 1"
            class="ml-1 text-gray-400 hover:text-rose-500"
            @click.stop="removeTargetChat(idx)"
          >×</span>
        </button>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="space-y-1.5"><label class="ui-label">{{ t('taskForm.chatSourceAccount') }}</label><CustomSelect v-model="selectedAccount" :options="selectedAccounts.map(a => ({label: a, value: a}))" /></div>
        <div class="space-y-1.5"><label class="ui-label flex items-center justify-between gap-2">{{ t('taskForm.selectFromList') }}<button type="button" @click="refreshChats" :disabled="chatListRefreshing || !selectedAccount" class="flex items-center gap-1 text-[10px] text-sky-500 hover:text-sky-700 dark:hover:text-sky-300 font-medium disabled:opacity-50 disabled:cursor-not-allowed"><RefreshCw class="w-3 h-3" :class="chatListRefreshing ? 'animate-spin' : ''" /> {{ t('taskForm.refreshChats') }}</button></label><CustomSelect v-model="selectedChatId" :disabled="chatListRefreshing" :options="[{label: chatListRefreshing ? t('taskForm.loadingChats') : t('taskForm.selectChat'), value:0}, ...availableChats.map(c => ({label: c.title || c.username || String(c.id), value: c.id}))]" @update:modelValue="selectedChatName = availableChats.find(c => c.id === $event)?.title || availableChats.find(c => c.id === $event)?.username || String($event)" /><p v-if="chatListError" class="text-xs text-amber-600 dark:text-amber-400 mt-1">{{ chatListError }}</p></div>
        <div class="space-y-1.5 relative"><label class="ui-label">{{ t('taskForm.searchChat') }}</label><div class="relative"><input v-model="chatSearch" :placeholder="t('taskForm.searchPlaceholder')" class="ui-input" /><div v-if="chatSearch.trim()" class="absolute top-11 left-0 right-0 z-10 max-h-40 overflow-y-auto ui-dropdown shadow-[var(--sp-shadow-md)]"><div v-if="chatSearchLoading" class="p-3 text-xs text-gray-400">{{ t('taskForm.searching') }}</div><template v-else><div v-for="chat in chatSearchResults" :key="chat.id" @click="selectChat(chat)" class="p-2 border-b border-gray-100 dark:border-gray-800/60 hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer text-sm"><div class="font-medium truncate">{{ chat.title || chat.username || chat.id }}</div><div class="text-[10px] text-gray-400 font-mono">{{ chat.id }}</div></div><div v-if="!chatSearchResults.length" class="p-3 text-xs text-gray-400">{{ t('taskForm.noResults') }}</div></template></div></div></div>
        <div class="space-y-1.5"><label class="ui-label">{{ t('taskForm.threadId') }}</label><input v-model="messageThreadId" :placeholder="t('taskForm.threadIdPlaceholder')" class="ui-input" /></div>
        <div class="space-y-1.5"><label class="ui-label">{{ t('taskForm.senderFilter') }}</label><input v-model="senderFilter" :placeholder="t('taskForm.senderFilterPlaceholder')" class="ui-input" /></div>
      </div>
    </div>
    <!-- 03 关键词监听（仅 listen） -->
    <div v-if="scheduleMode === 'listen'" class="ui-form-section !bg-[var(--sp-bg-elevated)]">
      <div class="ui-form-step mb-4">
        <span class="ui-form-step-num">03</span>
        <h4 class="ui-form-step-title text-emerald-600 dark:text-emerald-400">{{ t('taskForm.keywordListener') }}</h4>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="md:col-span-2 space-y-1.5"><label class="ui-label">{{ t('taskForm.keywords') }}</label><textarea v-model="listenerKeywords" rows="3" :placeholder="t('taskForm.keywordsPlaceholder')" class="ui-input !h-auto py-2.5"></textarea></div>
        <div class="space-y-1.5"><label class="ui-label">{{ t('taskForm.matchMode') }}</label><CustomSelect v-model="listenerMatchMode" :options="[{label: t('taskForm.matchContains'), value:'contains'}, {label: t('taskForm.matchExact'), value:'exact'}, {label: t('taskForm.matchRegex'), value:'regex'}]" /></div>
        <div class="space-y-1.5"><label class="ui-label">{{ t('taskForm.afterMatch') }}</label><CustomSelect v-model="listenerPushChannel" :options="[{label: t('taskForm.continueActions'), value:'continue'}, {label: t('taskForm.telegramNotify'), value:'telegram'}, {label: t('taskForm.forwardToChat'), value:'forward'}, {label: t('taskForm.barkPush'), value:'bark'}, {label: t('taskForm.customWebhook'), value:'custom'}]" /></div>
        <template v-if="listenerPushChannel === 'forward'"><div class="space-y-1.5"><label class="ui-label">{{ t('taskForm.forwardChatId') }}</label><input v-model="listenerForwardChatId" placeholder="-10012345678" class="ui-input" /></div><div class="space-y-1.5"><label class="ui-label">{{ t('taskForm.forwardThreadId') }}</label><input v-model="listenerForwardThreadId" :placeholder="t('taskForm.forwardThreadIdPlaceholder')" class="ui-input" /></div></template>
        <div v-if="listenerPushChannel === 'bark'" class="md:col-span-2 space-y-1.5"><label class="ui-label">{{ t('taskForm.barkUrl') }}</label><input v-model="listenerBarkUrl" placeholder="https://api.day.app/xxx" class="ui-input" /></div>
        <div v-if="listenerPushChannel === 'custom'" class="md:col-span-2 space-y-1.5"><label class="ui-label">{{ t('taskForm.webhookUrl') }}</label><input v-model="listenerCustomUrl" :placeholder="t('taskForm.webhookPlaceholder')" class="ui-input" /></div>
      </div>
    </div>
    <!-- 动作序列 -->
    <div v-if="scheduleMode === 'scheduled' || listenerPushChannel === 'continue'" class="ui-form-section !bg-[var(--sp-bg-elevated)]">
      <div class="ui-form-step mb-4">
        <span class="ui-form-step-num">{{ scheduleMode === 'listen' ? '04' : '03' }}</span>
        <h4 class="ui-form-step-title text-violet-600 dark:text-violet-400">{{ t('taskForm.actionSequence') }}</h4>
      </div>
      <div class="space-y-2">
        <div v-for="(action, idx) in actions" :key="action.id" class="flex items-center gap-2 p-2 sm:p-3 border border-gray-100 dark:border-gray-800/60 bg-gray-50/80 dark:bg-white/[0.02]">
          <!-- Action type select -->
          <div class="shrink-0 w-[120px] sm:w-[140px]">
            <CustomSelect v-model="action.type" :options="[
              {label: t('taskForm.sendText'), value:'send_text'},
              {label: t('taskForm.clickButton'), value:'click_text_button'},
              {label: t('taskForm.sendDice'), value:'send_dice'},
              {label: t('taskForm.botCmd'), value:'bot_cmd'},
              {label: t('taskForm.aiVision'), value:'_ai_vision', disabled:true},
              {label: t('taskForm.visionSend'), value:'vision_send', indent:true},
              {label: t('taskForm.visionClick'), value:'vision_click', indent:true},
              {label: t('taskForm.aiCalc'), value:'_ai_calc', disabled:true},
              {label: t('taskForm.calcSend'), value:'calc_send', indent:true},
              {label: t('taskForm.calcClick'), value:'calc_click', indent:true},
              {label: t('taskForm.delay'), value:'delay'},
            ]" className="w-full" />
          </div>
          <!-- Value input -->
          <div class="flex-1 min-w-0">
            <input v-if="action.type === 'send_text' || action.type === 'click_text_button'" v-model="action.value" :placeholder="t('taskForm.textPlaceholder')" class="ui-input !h-9 !text-xs !px-2" />
            <input v-else-if="action.type === 'delay'" v-model="action.value" :placeholder="t('taskForm.delayPlaceholder')" class="ui-input !h-9 !text-xs !px-2" />
            <input v-else-if="action.type === 'send_dice'" v-model="action.value" placeholder="🎲" class="ui-input !h-9 !text-xs !px-2" />
            <template v-else-if="action.type === 'bot_cmd'">
              <input v-model="action.value" :placeholder="t('taskForm.botUsernamePlaceholder')" class="ui-input !h-9 !text-xs !px-2" />
              <input v-model="action.commandPrefix" :placeholder="t('taskForm.commandPrefixPlaceholder')" class="ui-input !h-9 !text-xs !px-2 mt-1" />
            </template>
            <input v-else-if="['vision_send','vision_click','calc_send','calc_click'].includes(action.type)" v-model="action.aiPrompt" :placeholder="t('taskForm.aiPromptPlaceholder')" class="ui-input !h-9 !text-xs !px-2" />
            <span v-else class="h-9 flex items-center text-xs text-gray-400 px-2">-</span>
          </div>
          <!-- Move & Delete -->
          <div class="flex items-center gap-0.5 shrink-0">
            <button type="button" @click="moveAction(idx, -1)" class="p-1.5 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-white/[0.05] rounded-sm transition-colors"><ArrowUp class="w-3.5 h-3.5" /></button>
            <button type="button" @click="moveAction(idx, 1)" class="p-1.5 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-white/[0.05] rounded-sm transition-colors"><ArrowDown class="w-3.5 h-3.5" /></button>
            <button type="button" @click="removeAction(idx)" class="p-1.5 text-gray-400 hover:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-500/10 rounded-sm transition-colors"><Trash2 class="w-3.5 h-3.5" /></button>
          </div>
        </div>
        <button type="button" @click="addAction" class="flex items-center gap-1.5 px-3 py-2.5 text-xs text-gray-500 hover:text-sky-600 dark:hover:text-sky-400 border border-dashed border-gray-300 dark:border-gray-700 hover:border-sky-400/60 dark:hover:border-sky-500/40 hover:bg-sky-50/50 dark:hover:bg-sky-500/5 transition-colors w-full justify-center">
          <Plus class="w-3.5 h-3.5" /> {{ t('taskForm.addAction') }}
        </button>
      </div>
    </div>
  </div>
</template>
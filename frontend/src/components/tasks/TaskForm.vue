<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, computed } from 'vue'
import { ChevronDown } from 'lucide-vue-next'
import { listAccounts, getAccountChats, searchAccountChats } from '../../lib/api'
import { getAuthToken } from '../../lib/api/core'
import { useLatestResponseGuard } from '../../lib/latest-response'
import type { SignTask, AccountInfo, ChatInfo, CreateSignTaskRequest, UpdateSignTaskRequest, SignTaskChat } from '../../lib/api'
import CustomSelect from '../CustomSelect.vue'
import MultiSelect from '../MultiSelect.vue'
import TaskFormTargetSection from './TaskFormTargetSection.vue'
import TaskFormListenSection from './TaskFormListenSection.vue'
import TaskFormActionsSection from './TaskFormActionsSection.vue'
import type { TargetChatDraft } from './TaskFormTargetSection.vue'
import { useI18n } from '../../composables/useI18n'
import { useToast } from '../../composables/useToast'
import type { TaskActionItem, RawTaskAction } from '../../lib/types'
import { getErrorCode, getLocalizedErrorMessage } from '../../lib/types'
import { notifyApiError } from '../../lib/notify'
import { parseActions as parseActionsUtil, parseStepsToActions, nextActionId } from '../../lib/task-form-utils'
import { buildTaskFormPayload, buildTaskMetadataPatch, buildTargetFlowPatch, taskTargetKey } from '../../lib/task-form-payload'
import { devLog } from '../../lib/devLog'

const { t } = useI18n()
const toast = useToast()

const props = defineProps<{
  initialTask?: SignTask
  /** 新建时预填关联账号（来自账号卡片深链） */
  preferAccount?: string | null
  /**
   * 锁定任务名（仅真实「编辑已有任务」）。
   * 模板新建也会传 initialTask 作预填，但名称应可改、且需校验。
   */
  lockTaskName?: boolean
}>()
const accounts = ref<AccountInfo[]>([])
const selectedAccounts = ref<string[]>([])
const allAccountsMode = ref(false)
const accountOptions = computed(() => accounts.value.map(a => ({ label: a.name, value: a.name })))
const scheduleMode = ref<'scheduled' | 'listen'>('scheduled')
const timeRange = ref('08:00-19:00')
const taskName = ref('')
const retryCount = ref(3)
const executionEngine = ref("")
const executionEngineOptions = computed(() => [
  { label: t("taskForm.engineGlobal"), value: "" },
  { label: "PulseFlow (v4)", value: "v4" },
  { label: "Classic (v3)", value: "v3" },
])
/** 高级选项：重试 / 话题 ID / 发送者过滤，新建默认折叠 */
const showAdvanced = ref(false)
/** 任务名字段级提示（失焦后） */
const taskNameError = ref('')
/** 时间范围格式提示（定时模式，失焦后） */
const timeRangeError = ref('')
/** 新建多目标：shared=一任务多会话；split=按会话拆成独立任务 */
const createMode = ref<'shared' | 'split'>('shared')
const availableChats = ref<ChatInfo[]>([])
const chatSearch = ref('')
const chatSearchResults = ref<ChatInfo[]>([])
const chatSearchLoading = ref(false)
const chatListRefreshing = ref(false)
const chatListError = ref('')
/** 会话列表多选勾选（批量加入目标） */
const bulkSelectedChatIds = ref<number[]>([])
/** 多目标聊天（共享动作序列；build 时复制到每个 chat） */
let _chatDraftId = 0
const nextChatDraftId = () => ++_chatDraftId
const targetChats = ref<TargetChatDraft[]>([
  { id: nextChatDraftId(), chatId: 0, chatName: '', messageThreadId: '', senderFilter: '', sourceAccount: '' },
])
const activeChatIndex = ref(0)
const activeChat = computed(() => targetChats.value[activeChatIndex.value] || targetChats.value[0])
const editingExisting = computed(() => Boolean(props.initialTask && props.lockTaskName))
const draftReady = ref(false)
let initialDraft: CreateSignTaskRequest | undefined
const originalTargets = new Map<number, SignTaskChat>()
const initialTargets = new Map<number, TargetChatDraft>()
const flowDrafts = new Map<number, Partial<SignTaskChat>>()
const flowEditorEnabled = ref(false)
const activeRawTarget = computed(() => activeChat.value && originalTargets.get(activeChat.value.id))
const parseableRawActions = (raw: SignTaskChat | undefined): TaskActionItem[] | null => {
  if (!raw) return null
  if (Array.isArray(raw.actions) && raw.actions.length > 0) {
    return parseActionsUtil(raw.actions as RawTaskAction[])
  }
  if (Array.isArray(raw.steps)) {
    return parseStepsToActions(raw.steps)
  }
  return null
}
const canEditTargetFlow = computed(() => {
  const raw = activeRawTarget.value
  return Boolean(raw && !raw.flow_graph && parseableRawActions(raw))
})
const beginTargetFlowEdit = () => {
  if (!canEditTargetFlow.value || !activeChat.value) return
  flowEditorEnabled.value = false
  const saved = flowDrafts.get(activeChat.value.id)
  const raw = activeRawTarget.value
  const rawActions = (saved?.actions || raw?.actions || []) as RawTaskAction[]
  const listener = rawActions.find(action => action.action === 8)
  if (listener) {
    listenerKeywords.value = Array.isArray(listener.keywords) ? listener.keywords.join('\n') : ''
    listenerMatchMode.value = listener.match_mode || 'contains'
    listenerPushChannel.value = listener.push_channel || 'continue'
    listenerForwardChatId.value = String(listener.forward_chat_id || '')
    listenerForwardThreadId.value = String(listener.forward_message_thread_id || '')
    listenerBarkUrl.value = listener.bark_url || ''
    listenerCustomUrl.value = listener.custom_url || ''
    listenerServerChanKey.value = listener.server_chan_send_key || ''
    listenerIgnoreSelf.value = listener.ignore_self !== false
    listenerTimeWindowEnabled.value = Boolean(listener.active_time_start && listener.active_time_end)
    listenerActiveTimeStart.value = listener.active_time_start || '09:00'
    listenerActiveTimeEnd.value = listener.active_time_end || '19:00'
  }
  actions.value = listener
    ? parseActionsUtil(listener.continue_actions || rawActions)
    : (saved?.steps ? parseStepsToActions(saved.steps) : parseableRawActions(raw)) || []
  flowEditorEnabled.value = true
}
watch(activeChatIndex, () => { flowEditorEnabled.value = false }, { flush: 'sync' })
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
const adaptiveScheduleEnabled = ref(false)
const adaptiveSchedulePaddingSeconds = ref(30)
const adaptiveSchedulePatterns = ref<string[]>([])
const nextTaskOnSuccess = ref('')
const nextTaskDelaySeconds = ref<number | undefined>(2)
const listenerForwardChatId = ref('')
const listenerForwardThreadId = ref('')
const listenerBarkUrl = ref('')
const listenerCustomUrl = ref('')
const listenerServerChanKey = ref('')
/** 监听：忽略自己消息（默认开） */
const listenerIgnoreSelf = ref(true)
/** 监听时间窗 */
const listenerTimeWindowEnabled = ref(false)
const listenerActiveTimeStart = ref('09:00')
const listenerActiveTimeEnd = ref('22:00')
const actions = ref<TaskActionItem[]>([{ id: nextActionId(), type: 'send_text', value: '', aiPrompt: '' }])
/** 仅「编辑已有任务」为 true；模板预填新建不算编辑 */
const isEditing = computed(() => !!props.lockTaskName)

const MAX_TASK_TAGS = 20
const MAX_TASK_TAGS_TOTAL_LENGTH = 500
const taskTags = ref<string[]>([])
const tagsInput = ref("")
const tagsError = ref("")
const syncTagsFromInput = () => {
  tagsError.value = ""
  const parts = tagsInput.value.split(/[,，\s]+/).map(s => s.trim().slice(0, 50)).filter(Boolean)
  if (parts.length === 0) return
  const merged = Array.from(new Set([...taskTags.value, ...parts]))
  if (merged.length > MAX_TASK_TAGS) {
    tagsError.value = t("taskForm.tagsTooMany", { n: MAX_TASK_TAGS })
    return
  }
  if (merged.reduce((sum, s) => sum + s.length, 0) > MAX_TASK_TAGS_TOTAL_LENGTH) {
    tagsError.value = t("taskForm.tagsTooLong", { n: MAX_TASK_TAGS_TOTAL_LENGTH })
    return
  }
  taskTags.value = merged
  tagsInput.value = ""
}
const removeTag = (idx: number) => {
  taskTags.value.splice(idx, 1)
  tagsError.value = ""
}
const handleTagsKeydown = (e: KeyboardEvent) => {
  if (e.key === "Enter" || e.key === ",") {
    e.preventDefault()
    syncTagsFromInput()
  }
}

/** 编辑时若已有非默认高级字段，自动展开 */
const shouldAutoExpandAdvanced = () => {
  if (!props.initialTask) return false
  if (props.initialTask.next_task_on_success) return true
  if (props.initialTask.execution_engine || props.initialTask.chats?.[0]?.execution_engine) return true
  const retry = props.initialTask.retry_count
  if (retry != null && retry !== 3) return true
  for (const chat of props.initialTask.chats || []) {
    if (chat.message_thread_id) return true
    if (chat.sender_filter) return true
  }
  return false
}

const validateTaskName = () => {
  // 编辑已有任务：名称只读，不校验
  if (props.lockTaskName) {
    taskNameError.value = ''
    return
  }
  const name = taskName.value.trim()
  if (!name) {
    // 空白新建允许空名（自动生成）；模板预填名通常非空
    taskNameError.value = ''
    return
  }
  if (name.length > 80 || /[/\\]/.test(name)) {
    taskNameError.value = t('taskForm.taskNameInvalid')
    return
  }
  taskNameError.value = ''
}

const loadAccounts = async () => {
  try {
    const token = getAuthToken()
    const res = await listAccounts(token)
    accounts.value = res.accounts || []
    if (props.initialTask) {
      createMode.value = 'shared'
      taskName.value = props.initialTask.name || ''
      taskTags.value = Array.isArray(props.initialTask.tags) ? [...props.initialTask.tags] : []
      retryCount.value = props.initialTask.retry_count ?? 3
      adaptiveScheduleEnabled.value = Boolean(props.initialTask.adaptive_schedule_enabled)
      adaptiveSchedulePaddingSeconds.value = props.initialTask.adaptive_schedule_padding_seconds ?? 30
      adaptiveSchedulePatterns.value = Array.isArray(props.initialTask.adaptive_schedule_patterns)
        ? [...props.initialTask.adaptive_schedule_patterns]
        : []
      nextTaskOnSuccess.value = props.initialTask.next_task_on_success || ''
      nextTaskDelaySeconds.value = props.initialTask.next_task_delay_seconds ?? 2
      executionEngine.value = props.initialTask.execution_engine || ""
      showAdvanced.value = shouldAutoExpandAdvanced()
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
        targetChats.value.forEach((draft, index) => {
          originalTargets.set(draft.id, JSON.parse(JSON.stringify(props.initialTask!.chats[index])))
          initialTargets.set(draft.id, { ...draft })
        })
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
          listenerServerChanKey.value = la.server_chan_send_key || ''
          listenerIgnoreSelf.value = la.ignore_self !== false
          const hasWindow = !!(la.active_time_start && la.active_time_end)
          listenerTimeWindowEnabled.value = hasWindow
          if (hasWindow) {
            listenerActiveTimeStart.value = String(la.active_time_start)
            listenerActiveTimeEnd.value = String(la.active_time_end)
          }
          if (la.continue_actions) parseActions(la.continue_actions)
        } else if (primary.steps) {
          const parsedSteps = parseStepsToActions(primary.steps)
          if (parsedSteps && parsedSteps.length > 0) {
            actions.value = parsedSteps
            if (!primary.flow_graph) flowEditorEnabled.value = true
          } else if (primary.actions) {
            parseActions(primary.actions)
          }
        } else if (primary.actions) parseActions(primary.actions)
      } else if (selectedAccounts.value[0] || accounts.value[0]?.name) {
        targetChats.value[0].sourceAccount = selectedAccounts.value[0] || accounts.value[0]?.name || ''
      }
    } else {
      // 新建：优先深链账号，否则默认全选
      const prefer = (props.preferAccount || '').trim()
      if (prefer && accounts.value.some(a => a.name === prefer)) {
        allAccountsMode.value = false
        selectedAccounts.value = [prefer]
        targetChats.value[0].sourceAccount = prefer
      } else if (accounts.value.length > 0) {
        allAccountsMode.value = true
        selectedAccounts.value = accounts.value.map(a => a.name)
        targetChats.value[0].sourceAccount = selectedAccounts.value[0] || ''
      }
    }
    initialDraft = JSON.parse(JSON.stringify(buildPayload()))
    draftReady.value = true
    if (selectedAccount.value) loadChats(selectedAccount.value)
  } catch (e: unknown) {
    devLog.error(getLocalizedErrorMessage(e, t))
    notifyApiError(e, 'taskForm.loadAccountsFailed')
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
  const token = getAuthToken()
  try {
    const result = await getAccountChats(token, n, forceRefresh, controller.signal)
    if (controller.signal.aborted) return
    availableChats.value = result || []
  } catch (e: unknown) {
    if (controller.signal.aborted) return
    // 按后端稳定错误码判定会话失效，不按本地化文案匹配（英文界面中文子串永不命中）
    if (getErrorCode(e) === 'ACCOUNT_SESSION_INVALID') {
      chatListError.value = t('taskForm.sessionInvalid')
    } else {
      chatListError.value = t('taskForm.loadFailed')
    }
    availableChats.value = []
    if (forceRefresh) {
      notifyApiError(e, 'taskForm.loadChatsFailed')
    }
  } finally {
    if (loadChatsAbort === controller) { loadChatsAbort = null; chatListRefreshing.value = false }
  }
}
const refreshChats = async () => { if (!selectedAccount.value || chatListRefreshing.value) return; await loadChats(selectedAccount.value, true) }
watch(selectedAccounts, (v) => {
  if (v.length > 0 && !v.includes(selectedAccount.value)) {
    selectedAccount.value = v[0]
  } else if (v.length === 0) {
    selectedAccount.value = ''
    availableChats.value = []
  }
})
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
const chatSearchGuard = useLatestResponseGuard()
watch(chatSearch, (v) => {
  if (!v.trim()) {
    chatSearchResults.value = []
    return
  }
  if (st) clearTimeout(st)
  const seq = chatSearchGuard.next()
  st = setTimeout(async () => {
    chatSearchLoading.value = true
    try {
      const token = getAuthToken()
      const r = await searchAccountChats(token, selectedAccount.value, v.trim())
      if (!chatSearchGuard.isCurrent(seq)) return // 过期响应：输入已变化，丢弃
      chatSearchResults.value = r.items || []
    } catch (e: unknown) {
      if (!chatSearchGuard.isCurrent(seq)) return
      devLog.error('chat search failed', e)
    } finally {
      if (chatSearchGuard.isCurrent(seq)) chatSearchLoading.value = false
    }
  }, 300)
})
onUnmounted(() => {
  if (st) clearTimeout(st)
  loadChatsAbort?.abort() // 中止在途会话列表请求，避免写入已卸载组件
  chatSearchGuard.invalidate() // 使在途请求的 seq 失效，不再写入已卸载组件
})
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
const toggleBulkChat = (chatId: number) => {
  const set = new Set(bulkSelectedChatIds.value)
  if (set.has(chatId)) set.delete(chatId)
  else set.add(chatId)
  bulkSelectedChatIds.value = Array.from(set)
}
const applyBulkPickedChats = () => {
  if (!bulkSelectedChatIds.value.length) {
    toast.error(t('taskForm.noChatSelected'))
    return
  }
  const existing = new Set(targetChats.value.map(c => c.chatId).filter(Boolean))
  const source = selectedAccount.value || selectedAccounts.value[0] || ''
  let added = 0
  for (const id of bulkSelectedChatIds.value) {
    if (existing.has(id)) continue
    const chat = availableChats.value.find(c => c.id === id)
    const draft: TargetChatDraft = {
      id: nextChatDraftId(),
      chatId: id,
      chatName: chat?.title || chat?.username || String(id),
      messageThreadId: '',
      senderFilter: '',
      sourceAccount: source,
    }
    // 若当前唯一目标为空，先填第一个
    if (targetChats.value.length === 1 && !targetChats.value[0].chatId) {
      targetChats.value[0] = draft
    } else {
      targetChats.value.push(draft)
    }
    existing.add(id)
    added += 1
  }
  bulkSelectedChatIds.value = []
  if (added > 0) {
    activeChatIndex.value = targetChats.value.length - 1
  }
}
const addAction=()=>actions.value.push({id:nextActionId(),type:'send_text',value:'',aiPrompt:''})
const removeAction=(i:number)=>actions.value.splice(i,1)
const moveAction=(i:number,d:number)=>{if(i+d<0||i+d>=actions.value.length)return;const t=actions.value[i];actions.value[i]=actions.value[i+d];actions.value[i+d]=t}
const reorderAction = (from: number, to: number) => {
  if (from < 0 || from >= actions.value.length || to < 0 || to >= actions.value.length) return
  const item = actions.value.splice(from, 1)[0]
  actions.value.splice(to, 0, item)
}
/**
 * 交付单通道说明：
 * 历史版本存在 update:payload emit + payloadSnapshot computed 双通道，
 * 父组件（AddTaskModal/EditTaskModal）实际只走 buildPayload() 命令式通道，
 * 已删除冗余的 emit 通道；保存前父组件直接调 buildPayload() 同步取值，无防抖延迟。
 * createMode 不进 payload，父组件经 defineExpose 读取。
 */
const buildPayload = () => {
  syncTagsFromInput()
  return buildTaskFormPayload({
    taskName: taskName.value,
    selectedAccounts: selectedAccounts.value,
    allAccountsMode: allAccountsMode.value,
    scheduleMode: scheduleMode.value,
    timeRange: timeRange.value,
    retryCount: retryCount.value,
    targetChats: targetChats.value,
    fallbackChatId: selectedChatId.value || 0,
    fallbackChatName: selectedChatName.value || '',
    fallbackThreadId: messageThreadId.value || '',
    fallbackSenderFilter: senderFilter.value || '',
    fallbackSourceAccount: selectedAccount.value || '',
    actions: actions.value,
    listenerKeywords: listenerKeywords.value,
    listenerMatchMode: listenerMatchMode.value,
    listenerPushChannel: listenerPushChannel.value,
    listenerForwardChatId: listenerForwardChatId.value,
    listenerForwardThreadId: listenerForwardThreadId.value,
    listenerBarkUrl: listenerBarkUrl.value,
    listenerCustomUrl: listenerCustomUrl.value,
    listenerServerChanKey: listenerServerChanKey.value,
    listenerIgnoreSelf: listenerIgnoreSelf.value,
    listenerTimeWindowEnabled: listenerTimeWindowEnabled.value,
    listenerActiveTimeStart: listenerActiveTimeStart.value,
    listenerActiveTimeEnd: listenerActiveTimeEnd.value,
    tags: taskTags.value,
    adaptiveScheduleEnabled: adaptiveScheduleEnabled.value,
    adaptiveSchedulePaddingSeconds: adaptiveSchedulePaddingSeconds.value,
    adaptiveSchedulePatterns: adaptiveSchedulePatterns.value,
    nextTaskOnSuccess: nextTaskOnSuccess.value,
    nextTaskDelaySeconds: nextTaskDelaySeconds.value,
    executionEngine: executionEngine.value,
  })
}
const saveActiveFlowDraft = () => {
  if (!flowEditorEnabled.value || !activeChat.value) return
  const chat = buildPayload().chats[0]
  if (chat) flowDrafts.set(activeChat.value.id, {
    ...(chat.actions ? { actions: chat.actions } : {}),
    ...(chat.steps ? { steps: chat.steps } : {}),
    ...(chat.flow_graph ? { flow_graph: chat.flow_graph } : {}),
  })
}
watch(actions, saveActiveFlowDraft, { deep: true, flush: 'sync' })
watch([listenerKeywords, listenerMatchMode, listenerPushChannel, listenerForwardChatId,
  listenerForwardThreadId, listenerBarkUrl, listenerCustomUrl, listenerServerChanKey,
  listenerIgnoreSelf, listenerTimeWindowEnabled, listenerActiveTimeStart, listenerActiveTimeEnd],
saveActiveFlowDraft, { flush: 'sync' })

const buildMetadataPatch = (): UpdateSignTaskRequest => {
  if (!props.initialTask || !initialDraft || !draftReady.value) throw new Error('Task draft is still loading')
  return buildTaskMetadataPatch(props.initialTask, buildPayload(), initialDraft)
}
const buildFlowPatch = (targetKey: string): UpdateSignTaskRequest | null => {
  if (!props.initialTask) return null
  const entry = [...originalTargets.entries()].find(([, chat]) => taskTargetKey(chat) === targetKey)
  const flow = entry && flowDrafts.get(entry[0])
  return flow ? buildTargetFlowPatch(props.initialTask, targetKey, flow) : null
}
const buildUpdatePatch = (): UpdateSignTaskRequest => {
  const patch = buildMetadataPatch()
  const chats = targetChats.value.map((draft, index) => {
    const raw = originalTargets.get(draft.id)
    const initial = initialTargets.get(draft.id)
    if (!raw || !initial) return buildPayload().chats[index]!
    const updated = { ...raw }
    if (draft.chatId !== initial.chatId) updated.chat_id = draft.chatId
    if (draft.chatName !== initial.chatName) updated.name = draft.chatName
    if (draft.messageThreadId !== initial.messageThreadId) updated.message_thread_id = draft.messageThreadId ? Number(draft.messageThreadId) : undefined
    if (draft.senderFilter !== initial.senderFilter) updated.sender_filter = draft.senderFilter.trim() || undefined
    if (draft.sourceAccount !== initial.sourceAccount) updated.source_account = draft.sourceAccount || undefined
    const flow = flowDrafts.get(draft.id)
    if (flow) {
      for (const key of ['actions', 'steps', 'flow_graph', 'initial_step_id'] as const) delete updated[key]
      Object.assign(updated, flow)
    }
    return updated
  })
  if (JSON.stringify(chats) !== JSON.stringify(props.initialTask!.chats)) {
    patch.chats = chats
    patch.field_mask!.push('chats')
  }
  return patch
}
/** 供父组件提交前触发；返回是否通过 */
const validateForSubmit = (): boolean => {
  if (!draftReady.value) return false
  syncTagsFromInput()
  validateTaskName()
  validateTimeRange()
  return !taskNameError.value && !timeRangeError.value && !tagsError.value
}

/** 定时模式时间范围格式校验：HH:MM 或 HH:MM-HH:MM；监听模式不校验 */
const validateTimeRange = () => {
  if (scheduleMode.value === 'listen') {
    timeRangeError.value = ''
    return
  }
  const v = timeRange.value.trim()
  timeRangeError.value = /^\d{2}:\d{2}(-\d{2}:\d{2})?$/.test(v)
    ? ''
    : t('taskForm.timeRangeInvalid')
}
defineExpose({ buildPayload, buildMetadataPatch, buildFlowPatch, buildUpdatePatch, createMode, validateForSubmit })
onMounted(() => { loadAccounts() })
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
        <label class="ui-label-strong" for="task-form-name">{{ t('taskForm.taskName') }}</label>
        <input
          id="task-form-name"
          v-model="taskName"
          :placeholder="t('taskForm.taskNamePlaceholder')"
          :disabled="!!props.lockTaskName"
          class="ui-input disabled:opacity-50"
          :class="taskNameError ? '!border-rose-400 dark:!border-rose-500' : ''"
          :aria-invalid="!!taskNameError"
          @blur="validateTaskName"
        />
        <p v-if="taskNameError" class="text-[11px] text-rose-600 dark:text-rose-400">{{ taskNameError }}</p>
      </div>
      <div class="space-y-1.5">
        <label class="ui-label-strong">{{ t('taskForm.linkedAccounts') }}</label>
        <MultiSelect v-model="selectedAccounts" :options="accountOptions" :placeholder="t('taskForm.linkedAccountsPlaceholder')" :aria-label="t('taskForm.linkedAccounts')" :allMode="allAccountsMode" @update:allMode="allAccountsMode = $event" />
      </div>
      <div class="space-y-1.5">
        <label class="ui-label-strong">{{ t('taskForm.scheduleMode') }}</label>
        <CustomSelect v-model="scheduleMode" :aria-label="t('taskForm.scheduleMode')" :options="[{label: t('taskForm.scheduled'), value:'scheduled'}, {label: t('taskForm.listen'), value:'listen'}]" />
      </div>
      <div class="space-y-1.5">
        <label class="ui-label-strong" for="task-form-time-range">{{ t('taskForm.timeRange') }}</label>
        <input id="task-form-time-range" v-model="timeRange" :disabled="scheduleMode === 'listen'" :placeholder="scheduleMode === 'listen' ? t('taskForm.timeRangeListenPlaceholder') : t('taskForm.timeRangePlaceholder')" class="ui-input disabled:opacity-50 disabled:bg-[var(--sp-surface-subtle)] dark:disabled:bg-[var(--sp-terminal-bg)]" :class="timeRangeError ? '!border-rose-400 dark:!border-rose-500' : ''" :aria-invalid="!!timeRangeError" @blur="validateTimeRange" />
        <p v-if="timeRangeError" class="text-[10px] text-rose-600 dark:text-rose-400" role="alert">{{ timeRangeError }}</p>
      </div>
      <div class="space-y-1.5 md:col-span-2">
        <label class="ui-label-strong" for="task-form-tags">{{ t("taskForm.tags") || "分类标签" }}</label>
        <div class="flex items-center gap-2">
          <input
            id="task-form-tags"
            v-model="tagsInput"
            :placeholder="t('taskForm.tagsPlaceholder') || '输入标签后按回车或逗号添加（如：签到, 抽奖, daily）'"
            class="ui-input !h-9 !text-xs"
            @keydown="handleTagsKeydown"
            @blur="syncTagsFromInput"
          />
          <button
            type="button"
            class="ui-btn-secondary !h-9 !px-3 !text-xs shrink-0"
            @click="syncTagsFromInput"
          >
            {{ t("common.add") || "添加" }}
          </button>
        </div>
        <p v-if="tagsError" class="text-[10px] text-rose-600 dark:text-rose-400" role="alert">{{ tagsError }}</p>
        <div v-if="taskTags.length > 0" class="flex flex-wrap gap-1.5 pt-1">
          <span
            v-for="(tag, idx) in taskTags"
            :key="tag"
            class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-teal-50 text-teal-700 dark:bg-teal-950/50 dark:text-teal-300 border border-teal-200 dark:border-teal-800"
          >
            #{{ tag }}
            <button type="button" class="hover:text-rose-600 font-bold ml-0.5 cursor-pointer" @click="removeTag(idx)">&times;</button>
          </span>
        </div>
      </div>
    </div>
    <!-- 高级选项：重试等，降低主路径认知负担 -->
    <div class="mt-4 border-t border-[var(--sp-border)] dark:border-[var(--sp-border)] pt-3">
      <button
        type="button"
        class="inline-flex items-center gap-1 text-xs text-[var(--sp-text-secondary)] dark:text-[var(--sp-text-secondary)] hover:text-[var(--sp-text)] dark:hover:text-[var(--sp-text)]"
        :aria-expanded="showAdvanced"
        :aria-controls="'task-form-advanced'"
        @click="showAdvanced = !showAdvanced"
      >
        <ChevronDown class="w-3.5 h-3.5 transition-transform" :class="showAdvanced ? 'rotate-180' : ''" />
        {{ t('taskForm.advancedOptions') }}
      </button>
      <div v-if="showAdvanced" id="task-form-advanced" class="mt-3 grid grid-cols-1 md:grid-cols-2 gap-5">
        <div class="space-y-1.5">
          <label class="ui-label-strong" for="task-form-retry">{{ t('taskForm.retryCount') }}</label>
          <input id="task-form-retry" v-model.number="retryCount" type="number" min="0" max="99" class="ui-input" />
          <p class="text-[10px] text-[var(--sp-text-muted)] mt-1 leading-relaxed">{{ t('taskForm.retryCountHint') }}</p>
        </div>
        <div class="space-y-1.5">
          <label class="ui-label-strong" for="task-form-next-task">{{ t('taskForm.nextTaskOnSuccess') }}</label>
          <input
            id="task-form-next-task"
            v-model="nextTaskOnSuccess"
            type="text"
            class="ui-input"
            placeholder="任务名称（同账号下）"
          />
          <p class="text-[10px] text-[var(--sp-text-muted)] mt-1 leading-relaxed">{{ t('taskForm.nextTaskOnSuccessHint') }}</p>
        </div>
        <div class="space-y-1.5">
          <label class="ui-label-strong" for="task-form-next-task-delay">{{ t('taskForm.nextTaskDelaySeconds') }}</label>
          <input
            id="task-form-next-task-delay"
            v-model.number="nextTaskDelaySeconds"
            type="number"
            min="0"
            max="3600"
            step="1"
            class="ui-input"
            placeholder="2"
          />
          <p class="text-[10px] text-[var(--sp-text-muted)] mt-1 leading-relaxed">{{ t('taskForm.nextTaskDelaySecondsHint') }}</p>
        </div>
        <div class="space-y-1.5">
          <label class="ui-label-strong" for="task-form-execution-engine">{{ t('taskForm.executionEngine') }}</label>
          <CustomSelect
            id="task-form-execution-engine"
            :model-value="executionEngine"
            :options="executionEngineOptions"
            @update:model-value="executionEngine = String($event ?? '')"
          />
          <p class="text-[10px] text-[var(--sp-text-muted)] mt-1 leading-relaxed">{{ t('taskForm.executionEngineHint') }}</p>
        </div>
      </div>
    </div>
    </div>
    <!-- 02 目标会话 -->
    <TaskFormTargetSection
      :is-editing="isEditing"
      :create-mode="createMode"
      :target-chats="targetChats"
      :active-chat-index="activeChatIndex"
      :selected-account="selectedAccount"
      :selected-accounts="selectedAccounts"
      :selected-chat-id="selectedChatId"
      :message-thread-id="messageThreadId"
      :sender-filter="senderFilter"
      :show-advanced="showAdvanced"
      :available-chats="availableChats"
      :chat-search="chatSearch"
      :chat-search-results="chatSearchResults"
      :chat-search-loading="chatSearchLoading"
      :chat-list-refreshing="chatListRefreshing"
      :chat-list-error="chatListError"
      :bulk-selected-chat-ids="bulkSelectedChatIds"
      @add-target="addTargetChat"
      @remove-target="removeTargetChat"
      @update:active-chat-index="activeChatIndex = $event"
      @update:create-mode="createMode = $event"
      @update:selected-account="selectedAccount = $event"
      @update:selected-chat-id="selectedChatId = $event"
      @update:selected-chat-name="selectedChatName = $event"
      @update:message-thread-id="messageThreadId = $event"
      @update:sender-filter="senderFilter = $event"
      @update:chat-search="chatSearch = $event"
      @refresh-chats="refreshChats"
      @select-chat="selectChat"
      @toggle-bulk-chat="toggleBulkChat"
      @apply-bulk-picked="applyBulkPickedChats"
    />
    <div v-if="editingExisting" class="ui-alert-info" data-testid="preserved-flow-summary">
      <p>{{ t('taskForm.preservedFlowSummary', { target: activeRawTarget?.name || activeRawTarget?.chat_id || '' }) }}</p>
      <p v-if="activeRawTarget?.flow_graph || (activeRawTarget?.steps && !canEditTargetFlow)">{{ t('taskForm.advancedFlowPreserved') }}</p>
      <button v-if="canEditTargetFlow && !flowEditorEnabled" type="button" class="ui-btn-secondary mt-2" @click="beginTargetFlowEdit">{{ t('taskForm.editTargetFlow') }}</button>
    </div>
    <!-- 03 关键词监听（仅 listen） -->
    <TaskFormListenSection
      v-if="scheduleMode === 'listen' && (!editingExisting || flowEditorEnabled)"
      :keywords="listenerKeywords"
      :match-mode="listenerMatchMode"
      :push-channel="listenerPushChannel"
      :ignore-self="listenerIgnoreSelf"
      :time-window-enabled="listenerTimeWindowEnabled"
      :active-time-start="listenerActiveTimeStart"
      :active-time-end="listenerActiveTimeEnd"
      :forward-chat-id="listenerForwardChatId"
      :forward-thread-id="listenerForwardThreadId"
      :bark-url="listenerBarkUrl"
      :server-chan-key="listenerServerChanKey"
      :custom-url="listenerCustomUrl"
      @update:keywords="listenerKeywords = $event"
      @update:match-mode="listenerMatchMode = $event"
      @update:push-channel="listenerPushChannel = $event"
      @update:ignore-self="listenerIgnoreSelf = $event"
      @update:time-window-enabled="listenerTimeWindowEnabled = $event"
      @update:active-time-start="listenerActiveTimeStart = $event"
      @update:active-time-end="listenerActiveTimeEnd = $event"
      @update:forward-chat-id="listenerForwardChatId = $event"
      @update:forward-thread-id="listenerForwardThreadId = $event"
      @update:bark-url="listenerBarkUrl = $event"
      @update:server-chan-key="listenerServerChanKey = $event"
      @update:custom-url="listenerCustomUrl = $event"
    />
    <!-- 动作序列 -->
    <TaskFormActionsSection
      v-if="(!editingExisting || flowEditorEnabled) && (scheduleMode === 'scheduled' || listenerPushChannel === 'continue')"
      :actions="actions"
      :step-num="scheduleMode === 'listen' ? '04' : '03'"
      :allow-custom-plugin="true"
      :adaptive-schedule-enabled="adaptiveScheduleEnabled"
      :adaptive-schedule-padding-seconds="adaptiveSchedulePaddingSeconds"
      :adaptive-schedule-patterns="adaptiveSchedulePatterns"
      @update:adaptive-schedule-enabled="adaptiveScheduleEnabled = $event"
      @update:adaptive-schedule-padding-seconds="adaptiveSchedulePaddingSeconds = $event"
      @update:adaptive-schedule-patterns="adaptiveSchedulePatterns = $event"
      @add="addAction"
      @remove="removeAction"
      @move="moveAction"
      @reorder="reorderAction"
    />
  </div>
</template>

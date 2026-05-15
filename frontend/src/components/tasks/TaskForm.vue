<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { Plus, Trash2, ArrowUp, ArrowDown, RefreshCw } from 'lucide-vue-next'
import { listAccounts, getAccountChats, searchAccountChats } from '../../lib/api'
import CustomSelect from '../CustomSelect.vue'
import MultiSelect from '../MultiSelect.vue'
import { useI18n } from '../../composables/useI18n'

const { t } = useI18n()

const props = defineProps<{ initialTask?: any }>()
const emit = defineEmits<{ (e: 'update:payload', value: any): void }>()
const accounts = ref<any[]>([])
const selectedAccounts = ref<string[]>([])
const selectedAccount = ref('')
const accountOptions = computed(() => accounts.value.map(a => ({ label: a.name, value: a.name })))
const scheduleMode = ref<'scheduled' | 'listen'>('scheduled')
const timeRange = ref('08:00-19:00')
const taskName = ref('')
const availableChats = ref<any[]>([])
const chatSearch = ref('')
const chatSearchResults = ref<any[]>([])
const chatSearchLoading = ref(false)
const chatListRefreshing = ref(false)
const selectedChatId = ref<number>(0)
const selectedChatName = ref('')
const messageThreadId = ref('')
const listenerKeywords = ref('')
const listenerMatchMode = ref('contains')
const listenerPushChannel = ref('continue')
const listenerForwardChatId = ref('')
const listenerForwardThreadId = ref('')
const listenerBarkUrl = ref('')
const listenerCustomUrl = ref('')
const actions = ref<any[]>([{ id: Date.now(), type: 'send_text', value: '', aiPrompt: '' }])

const loadAccounts = async () => {
  try {
    const token = localStorage.getItem('tg-signer-token') || ''
    const res = await listAccounts(token)
    accounts.value = res.accounts || []
    if (props.initialTask) {
      taskName.value = props.initialTask.name || ''
      scheduleMode.value = props.initialTask.execution_mode === 'listen' ? 'listen' : 'scheduled'
      if (props.initialTask.execution_mode === 'range') timeRange.value = props.initialTask.range_start + '-' + props.initialTask.range_end
      else timeRange.value = props.initialTask.sign_at || '08:00-19:00'
      const taskAccs = props.initialTask.account_names?.length ? props.initialTask.account_names : [props.initialTask.account_name]
      selectedAccounts.value = taskAccs.filter((a: string) => accounts.value.some(acc => acc.name === a))
      selectedAccount.value = selectedAccounts.value[0] || ''
      if (props.initialTask.chats?.length > 0) {
        const chat = props.initialTask.chats[0]
        selectedChatId.value = Number(chat.chat_id) || 0
        selectedChatName.value = chat.name || ''
        messageThreadId.value = chat.message_thread_id ? String(chat.message_thread_id) : ''
        const la = chat.actions?.find((a: any) => a.action === 8)
        if (la) {
          listenerKeywords.value = Array.isArray(la.keywords) ? la.keywords.join('\n') : ''
          listenerMatchMode.value = la.match_mode || 'contains'
          listenerPushChannel.value = la.push_channel || 'continue'
          listenerForwardChatId.value = la.forward_chat_id ? String(la.forward_chat_id) : ''
          listenerForwardThreadId.value = la.forward_message_thread_id ? String(la.forward_message_thread_id) : ''
          listenerBarkUrl.value = la.bark_url || ''
          listenerCustomUrl.value = la.custom_url || ''
          if (la.continue_actions) parseActions(la.continue_actions)
        } else if (chat.actions) parseActions(chat.actions)
      }
    } else {
      if (accounts.value.length > 0) { selectedAccounts.value = accounts.value.map(a => a.name); selectedAccount.value = selectedAccounts.value[0] || '' }
    }
    if (selectedAccount.value) loadChats(selectedAccount.value)
  } catch (e) { console.error(e) }
}
const parseActions = (raw: any[]) => { const p: any[] = []; for (const a of raw) { if (a.delay) p.push({id:Date.now()+Math.random(),type:'delay',value:String(a.delay),aiPrompt:''}); if(a.action===1)p.push({id:Date.now()+Math.random(),type:'send_text',value:a.text||'',aiPrompt:''}); else if(a.action===3)p.push({id:Date.now()+Math.random(),type:'click_text_button',value:a.text||'',aiPrompt:''}); else if(a.action===4)p.push({id:Date.now()+Math.random(),type:'vision_click',value:'',aiPrompt:a.ai_prompt||''}); else if(a.action===5)p.push({id:Date.now()+Math.random(),type:'calc_send',value:'',aiPrompt:a.ai_prompt||''}); else if(a.action===6)p.push({id:Date.now()+Math.random(),type:'vision_send',value:'',aiPrompt:a.ai_prompt||''}); else if(a.action===7)p.push({id:Date.now()+Math.random(),type:'calc_click',value:'',aiPrompt:a.ai_prompt||''}); } if(p.length>0)actions.value=p }
let loadChatsAbort: AbortController | null = null
const loadChats = async (n: string, forceRefresh: boolean = false) => {
  // Cancel previous request to avoid race conditions
  if (loadChatsAbort) { loadChatsAbort.abort(); loadChatsAbort = null }
  const controller = new AbortController()
  loadChatsAbort = controller
  chatListRefreshing.value = true
  const token = localStorage.getItem('tg-signer-token')||''
  try {
    const result = await getAccountChats(token, n, forceRefresh)
    if (controller.signal.aborted) return
    availableChats.value = result || []
  } catch(e: any) {
    if (controller.signal.aborted) return
    console.error('loadChats failed:', e)
    availableChats.value = []
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
let st:any=null
watch(chatSearch,(v)=>{if(!v.trim()){chatSearchResults.value=[];return};if(st)clearTimeout(st);st=setTimeout(async()=>{chatSearchLoading.value=true;try{const t=localStorage.getItem('tg-signer-token')||'';const r=await searchAccountChats(t,selectedAccount.value,v.trim());chatSearchResults.value=r.items||[]}catch(e){console.error(e)}finally{chatSearchLoading.value=false}},300)})
const selectChat=(c:any)=>{selectedChatId.value=c.id;selectedChatName.value=c.title||c.username||String(c.id);chatSearch.value='';chatSearchResults.value=[]}
const addAction=()=>actions.value.push({id:Date.now(),type:'send_text',value:'',aiPrompt:''})
const removeAction=(i:number)=>actions.value.splice(i,1)
const moveAction=(i:number,d:number)=>{if(i+d<0||i+d>=actions.value.length)return;const t=actions.value[i];actions.value[i]=actions.value[i+d];actions.value[i+d]=t}
const buildPayload=()=>{let em='fixed',sa='08:00',rs='',re='';if(scheduleMode.value==='listen')em='listen';else{const p=timeRange.value.split('-');if(p.length===2){em='range';rs=p[0].trim();re=p[1].trim();sa=rs}else sa=timeRange.value.trim()||'08:00'}
const ba:any[]=[];for(const a of actions.value){const o:any={};if(a.type==='delay')continue;if(a.type==='send_text'){o.action=1;o.text=a.value}else if(a.type==='send_dice'){o.action=2;o.dice=a.value||'\uD83C\uDFB2'}else if(a.type==='click_text_button'){o.action=3;o.text=a.value}else if(a.type==='vision_click'){o.action=4;if(a.aiPrompt)o.ai_prompt=a.aiPrompt}else if(a.type==='calc_send'){o.action=5;if(a.aiPrompt)o.ai_prompt=a.aiPrompt}else if(a.type==='vision_send'){o.action=6;if(a.aiPrompt)o.ai_prompt=a.aiPrompt}else if(a.type==='calc_click'){o.action=7;if(a.aiPrompt)o.ai_prompt=a.aiPrompt};const prev=actions.value[actions.value.indexOf(a)-1];if(prev&&prev.type==='delay'&&prev.value)o.delay=prev.value;ba.push(o)}
let ca=ba;if(scheduleMode.value==='listen'){const kw=listenerKeywords.value.split('\n').map((k: string)=>k.trim()).filter(Boolean);const la:any={action:8,keywords:kw,match_mode:listenerMatchMode.value,push_channel:listenerPushChannel.value};if(listenerPushChannel.value==='forward'){if(listenerForwardChatId.value)la.forward_chat_id=listenerForwardChatId.value;if(listenerForwardThreadId.value)la.forward_message_thread_id=listenerForwardThreadId.value};if(listenerPushChannel.value==='bark'&&listenerBarkUrl.value)la.bark_url=listenerBarkUrl.value;if(listenerPushChannel.value==='custom'&&listenerCustomUrl.value)la.custom_url=listenerCustomUrl.value;if(listenerPushChannel.value==='continue'&&ba.length>0)la.continue_actions=ba;ca=[la]}
return{name:taskName.value||selectedChatName.value||`task_${Date.now()}`,account_name:selectedAccounts.value[0]||'',account_names:selectedAccounts.value,sign_at:sa,execution_mode:em,range_start:rs,range_end:re,random_seconds:0,chats:[{chat_id:selectedChatId.value,name:selectedChatName.value,actions:ca,message_thread_id:messageThreadId.value?Number(messageThreadId.value):undefined}]}}
watch([taskName,selectedAccounts,scheduleMode,timeRange,selectedChatId,selectedChatName,messageThreadId,actions,listenerKeywords,listenerMatchMode,listenerPushChannel,listenerForwardChatId,listenerForwardThreadId,listenerBarkUrl,listenerCustomUrl],()=>{emit('update:payload',buildPayload())},{deep:true})
onMounted(()=>{loadAccounts()})
</script>
<template>
  <div class="space-y-6 text-left">
    <div class="grid grid-cols-1 md:grid-cols-2 gap-5 p-4 border border-gray-200 dark:border-gray-800/60 bg-gray-50/50 dark:bg-gray-900/40">
      <div class="space-y-1.5">
        <label class="text-xs font-semibold text-gray-500 tracking-wide uppercase">{{ t('taskForm.taskName') }}</label>
        <input v-model="taskName" :placeholder="t('taskForm.taskNamePlaceholder')" :disabled="!!props.initialTask" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-gray-400 disabled:opacity-50" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-semibold text-gray-500 tracking-wide uppercase">{{ t('taskForm.linkedAccounts') }}</label>
        <MultiSelect v-model="selectedAccounts" :options="accountOptions" :placeholder="t('taskForm.linkedAccountsPlaceholder')" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-semibold text-gray-500 tracking-wide uppercase">{{ t('taskForm.scheduleMode') }}</label>
        <CustomSelect v-model="scheduleMode" :options="[{label: t('taskForm.scheduled'), value:'scheduled'}, {label: t('taskForm.listen'), value:'listen'}]" />
      </div>
      <div class="space-y-1.5">
        <label class="text-xs font-semibold text-gray-500 tracking-wide uppercase">{{ t('taskForm.timeRange') }}</label>
        <input v-model="timeRange" :disabled="scheduleMode === 'listen'" :placeholder="scheduleMode === 'listen' ? '24H' : t('taskForm.timeRangePlaceholder')" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-gray-400 disabled:opacity-50 disabled:bg-gray-50 dark:disabled:bg-gray-950" />
      </div>
    </div>
    <div class="p-4 border border-sky-100 dark:border-gray-800/60 bg-sky-50/50 dark:bg-gray-900/40">
      <h4 class="mb-4 text-xs font-bold uppercase tracking-widest text-sky-500">{{ t('taskForm.targetChat') }}</h4>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="space-y-1.5"><label class="text-xs font-medium text-gray-500">{{ t('taskForm.chatSourceAccount') }}</label><CustomSelect v-model="selectedAccount" :options="selectedAccounts.map(a => ({label: a, value: a}))" /></div>
        <div class="space-y-1.5"><label class="text-xs font-medium text-gray-500 flex items-center justify-between">{{ t('taskForm.selectFromList') }}<button type="button" @click="refreshChats" :disabled="chatListRefreshing || !selectedAccount" class="flex items-center gap-1 text-[10px] text-sky-500 hover:text-sky-700 dark:hover:text-sky-300 font-medium disabled:opacity-50 disabled:cursor-not-allowed"><RefreshCw class="w-3 h-3" :class="chatListRefreshing ? 'animate-spin' : ''" /> {{ t('taskForm.refreshChats') }}</button></label><CustomSelect v-model="selectedChatId" :disabled="chatListRefreshing" :options="[{label: chatListRefreshing ? t('taskForm.loadingChats') : t('taskForm.selectChat'), value:0}, ...availableChats.map(c => ({label: c.title || c.username || c.id, value: c.id}))]" @update:modelValue="selectedChatName = availableChats.find(c => c.id === $event)?.title || availableChats.find(c => c.id === $event)?.username || String($event)" /></div>
        <div class="space-y-1.5 relative"><label class="text-xs font-medium text-gray-500">{{ t('taskForm.searchChat') }}</label><div class="relative"><input v-model="chatSearch" :placeholder="t('taskForm.searchPlaceholder')" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-gray-400" /><div v-if="chatSearch.trim()" class="absolute top-11 left-0 right-0 z-10 max-h-40 overflow-y-auto bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 shadow-lg"><div v-if="chatSearchLoading" class="p-3 text-xs text-gray-400">{{ t('taskForm.searching') }}</div><template v-else><div v-for="chat in chatSearchResults" :key="chat.id" @click="selectChat(chat)" class="p-2 border-b border-gray-100 dark:border-gray-800/60 hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer text-sm"><div class="font-medium truncate">{{ chat.title || chat.username || chat.id }}</div><div class="text-[10px] text-gray-400 font-mono">{{ chat.id }}</div></div><div v-if="!chatSearchResults.length" class="p-3 text-xs text-gray-400">{{ t('taskForm.noResults') }}</div></template></div></div></div>
        <div class="space-y-1.5"><label class="text-xs font-medium text-gray-500">{{ t('taskForm.threadId') }}</label><input v-model="messageThreadId" :placeholder="t('taskForm.threadIdPlaceholder')" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-gray-400" /></div>
      </div>
    </div>
    <div v-if="scheduleMode === 'listen'" class="p-4 border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900">
      <h4 class="mb-4 text-xs font-bold uppercase tracking-widest text-emerald-500">{{ t('taskForm.keywordListener') }}</h4>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="md:col-span-2 space-y-1.5"><label class="text-xs font-medium text-gray-500">{{ t('taskForm.keywords') }}</label><textarea v-model="listenerKeywords" rows="3" :placeholder="t('taskForm.keywordsPlaceholder')" class="w-full p-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-gray-400"></textarea></div>
        <div class="space-y-1.5"><label class="text-xs font-medium text-gray-500">{{ t('taskForm.matchMode') }}</label><CustomSelect v-model="listenerMatchMode" :options="[{label: t('taskForm.matchContains'), value:'contains'}, {label: t('taskForm.matchExact'), value:'exact'}, {label: t('taskForm.matchRegex'), value:'regex'}]" /></div>
        <div class="space-y-1.5"><label class="text-xs font-medium text-gray-500">{{ t('taskForm.afterMatch') }}</label><CustomSelect v-model="listenerPushChannel" :options="[{label: t('taskForm.continueActions'), value:'continue'}, {label: t('taskForm.telegramNotify'), value:'telegram'}, {label: t('taskForm.forwardToChat'), value:'forward'}, {label: t('taskForm.barkPush'), value:'bark'}, {label: t('taskForm.customWebhook'), value:'custom'}]" /></div>
        <template v-if="listenerPushChannel === 'forward'"><div class="space-y-1.5"><label class="text-xs font-medium text-gray-500">{{ t('taskForm.forwardChatId') }}</label><input v-model="listenerForwardChatId" placeholder="-10012345678" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-gray-400" /></div><div class="space-y-1.5"><label class="text-xs font-medium text-gray-500">{{ t('taskForm.forwardThreadId') }}</label><input v-model="listenerForwardThreadId" :placeholder="t('taskForm.forwardThreadIdPlaceholder')" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-gray-400" /></div></template>
        <div v-if="listenerPushChannel === 'bark'" class="md:col-span-2 space-y-1.5"><label class="text-xs font-medium text-gray-500">{{ t('taskForm.barkUrl') }}</label><input v-model="listenerBarkUrl" placeholder="https://api.day.app/xxx" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-gray-400" /></div>
        <div v-if="listenerPushChannel === 'custom'" class="md:col-span-2 space-y-1.5"><label class="text-xs font-medium text-gray-500">{{ t('taskForm.webhookUrl') }}</label><input v-model="listenerCustomUrl" :placeholder="t('taskForm.webhookPlaceholder')" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-gray-400" /></div>
      </div>
    </div>
    <div v-if="scheduleMode === 'scheduled' || listenerPushChannel === 'continue'" class="p-4 border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900">
      <h4 class="mb-4 text-xs font-bold uppercase tracking-widest text-violet-500">{{ t('taskForm.actionSequence') }}</h4>
      <div class="space-y-2">
        <div v-for="(action, idx) in actions" :key="action.id" class="flex items-center gap-2 p-2 sm:p-3 border border-gray-100 dark:border-gray-800/60 bg-gray-50/50 dark:bg-gray-950/50">
          <!-- Action type select -->
          <div class="shrink-0 w-[120px] sm:w-[140px]">
            <CustomSelect v-model="action.type" :options="[
              {label: t('taskForm.sendText'), value:'send_text'},
              {label: t('taskForm.clickButton'), value:'click_text_button'},
              {label: t('taskForm.sendDice'), value:'send_dice'},
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
            <input v-if="action.type === 'send_text' || action.type === 'click_text_button'" v-model="action.value" :placeholder="t('taskForm.textPlaceholder')" class="w-full h-9 px-2 text-xs border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-gray-400" />
            <input v-else-if="action.type === 'delay'" v-model="action.value" :placeholder="t('taskForm.delayPlaceholder')" class="w-full h-9 px-2 text-xs border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-gray-400" />
            <input v-else-if="action.type === 'send_dice'" v-model="action.value" placeholder="🎲" class="w-full h-9 px-2 text-xs border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-gray-400" />
            <input v-else-if="['vision_send','vision_click','calc_send','calc_click'].includes(action.type)" v-model="action.aiPrompt" :placeholder="t('taskForm.aiPromptPlaceholder')" class="w-full h-9 px-2 text-xs border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-gray-400" />
            <span v-else class="h-9 flex items-center text-xs text-gray-400 px-2">-</span>
          </div>
          <!-- Move & Delete -->
          <div class="flex items-center gap-0.5 shrink-0">
            <button type="button" @click="moveAction(idx, -1)" class="p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"><ArrowUp class="w-3.5 h-3.5" /></button>
            <button type="button" @click="moveAction(idx, 1)" class="p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"><ArrowDown class="w-3.5 h-3.5" /></button>
            <button type="button" @click="removeAction(idx)" class="p-1 text-gray-400 hover:text-rose-500"><Trash2 class="w-3.5 h-3.5" /></button>
          </div>
        </div>
        <button type="button" @click="addAction" class="flex items-center gap-1.5 px-3 py-2 text-xs text-gray-500 hover:text-gray-900 dark:hover:text-gray-200 border border-dashed border-gray-300 dark:border-gray-700 hover:border-gray-400 dark:hover:border-gray-600 transition-colors w-full justify-center">
          <Plus class="w-3.5 h-3.5" /> {{ t('taskForm.addAction') }}
        </button>
      </div>
    </div>
  </div>
</template>
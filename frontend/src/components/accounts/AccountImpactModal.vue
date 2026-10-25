<script setup lang="ts">
import Modal from '../Modal.vue'
import type { AccountChangePlan } from '../../lib/api/accounts'

defineProps<{ isOpen: boolean; plan: AccountChangePlan | null; loading: boolean; error?: string }>()
defineEmits<{ close: []; apply: [] }>()
</script>

<template>
  <Modal :isOpen="isOpen" title="Account change impact / 账号变更影响" @close="$emit('close')">
    <div v-if="plan" class="space-y-4">
      <p class="font-semibold">{{ plan.old_name }} → {{ plan.operation === 'delete' ? 'Delete / 删除' : plan.new_name }}</p>
      <dl class="space-y-2 text-sm">
        <div><dt class="ui-label">Tasks / 任务 ({{ plan.affected_tasks.length }})</dt><dd>{{ plan.affected_tasks.map(task => task.name).join(', ') || '—' }}</dd></div>
        <div><dt class="ui-label">Jobs / 调度 ({{ plan.affected_jobs.length }})</dt><dd>{{ plan.affected_jobs.join(', ') || '—' }}</dd></div>
        <div><dt class="ui-label">Monitors / 监听 ({{ plan.affected_monitors.length }})</dt><dd>{{ plan.affected_monitors.join(', ') || '—' }}</dd></div>
        <div><dt class="ui-label">History / 历史 ({{ plan.history_paths.length }})</dt><dd>{{ plan.history_policy === 'retain' ? 'Retain / 保留' : 'Delete permanently / 永久删除' }}</dd></div>
        <div><dt class="ui-label">Plugin storage / 插件存储</dt><dd>{{ plan.plugin_namespaces.join(', ') }}</dd></div>
      </dl>
      <ul class="ui-alert-warning space-y-1 text-sm"><li v-for="warning in plan.warnings" :key="warning">{{ warning }}</li></ul>
      <p v-if="error" class="ui-alert-error" role="alert">{{ error }}</p>
      <div class="flex justify-end gap-3">
        <button class="ui-btn-secondary" type="button" :disabled="loading" @click="$emit('close')">Cancel / 取消</button>
        <button class="ui-btn-primary" type="button" :disabled="loading" @click="$emit('apply')">{{ loading ? 'Applying… / 执行中…' : 'Confirm change / 确认变更' }}</button>
      </div>
    </div>
  </Modal>
</template>

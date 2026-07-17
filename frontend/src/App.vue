<script setup lang="ts">
import GlobalToast from './components/GlobalToast.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import CommandPalette from './components/CommandPalette.vue'
</script>

<template>
  <router-view />
  <GlobalToast />
  <ConfirmDialog />
  <CommandPalette />
</template>

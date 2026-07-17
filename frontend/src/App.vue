<script setup lang="ts">
import GlobalToast from './components/GlobalToast.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
</script>

<template>
  <router-view />
  <GlobalToast />
  <ConfirmDialog />
</template>

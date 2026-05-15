<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { LayoutDashboard, Users, Zap, Terminal, Settings, UserCircle, Github, Globe, Moon, Sun, Menu } from 'lucide-vue-next'
import { useTheme } from '../composables/useTheme'
import { useI18n } from '../composables/useI18n'
import UserProfileModal from '../components/settings/UserProfileModal.vue'

const route = useRoute()
const { isDark, toggleTheme } = useTheme()
const { toggleLanguage, t } = useI18n()
const isMobileMenuOpen = ref(false)
const showProfileModal = ref(false)

const navigation = [
  { id: 'dashboard', name: 'dashboard', icon: LayoutDashboard, labelKey: 'nav.dashboard' },
  { id: 'accounts', name: 'accounts', icon: Users, labelKey: 'nav.accounts' },
  { id: 'tasks', name: 'tasks', icon: Zap, labelKey: 'nav.tasks' },
  { id: 'logs', name: 'logs', icon: Terminal, labelKey: 'nav.logs' },
  { id: 'settings', name: 'settings', icon: Settings, labelKey: 'nav.settings' },
]

const currentTitle = computed(() => {
  const current = navigation.find(n => n.name === route.name)
  if (!current) return 'TG-SignPulse'
  return t(current.labelKey)
})

const openGithub = () => {
  window.open('https://github.com/akasls/TG-SignPulse', '_blank')
}

const handleNavClick = () => {
  isMobileMenuOpen.value = false
}
</script>

<template>
  <div class="flex min-h-screen w-full overflow-x-hidden bg-gray-50 dark:bg-gray-950 text-gray-700 dark:text-gray-300 font-sans">
    
    <!-- Mobile Menu Overlay -->
    <div v-if="isMobileMenuOpen" class="fixed inset-0 bg-gray-900/40 dark:bg-black/60 backdrop-blur-sm z-40 lg:hidden" @click="isMobileMenuOpen = false"></div>

    <!-- Sidebar -->
    <!-- PC端固定 w-64，移动端抽屉式滑动 -->
    <aside 
      class="fixed inset-y-0 left-0 z-50 flex flex-col bg-white dark:bg-gray-950 border-r border-gray-200 dark:border-gray-800/60 transition-transform duration-300 ease-in-out w-64"
      :class="isMobileMenuOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'"
    >
      <div class="flex items-center h-16 px-5 border-b border-gray-200 dark:border-gray-800/60">
        <div class="w-6 h-6 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-950 flex items-center justify-center shrink-0 font-bold text-xs tracking-tighter">TG</div>
        <span class="ml-4 font-mono font-medium tracking-widest text-gray-900 dark:text-gray-100 whitespace-nowrap">SIGNPULSE</span>
      </div>

      <nav class="flex-1 py-6 flex flex-col gap-2 px-3 overflow-y-auto custom-scrollbar">
        <router-link 
          v-for="nav in navigation" 
          :key="nav.id"
          :to="{ name: nav.name }"
          @click="handleNavClick"
          class="flex items-center h-10 px-2.5 transition-colors whitespace-nowrap"
          :class="route.name === nav.name ? 'bg-gray-100 dark:bg-gray-900 text-gray-900 dark:text-gray-100' : 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-900/50'"
        >
          <component :is="nav.icon" class="w-5 h-5 shrink-0" stroke-width="1.5" />
          <span class="ml-4 text-sm font-medium">{{ t(nav.labelKey) }}</span>
        </router-link>
      </nav>

      <!-- User Center (Bottom) -->
      <div class="border-t border-gray-200 dark:border-gray-800/60 p-3">
        <button @click="showProfileModal = true; isMobileMenuOpen = false" class="flex items-center w-full h-10 px-2.5 transition-colors whitespace-nowrap text-gray-500 hover:text-gray-900 dark:hover:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-900/50">
          <UserCircle class="w-5 h-5 shrink-0" stroke-width="1.5" />
          <span class="ml-4 text-sm font-medium">{{ t('nav.profile') }}</span>
        </button>
      </div>
    </aside>

    <!-- Main Content -->
    <!-- PC端左侧留白 pl-64, 移动端 pl-0 -->
    <main class="flex-1 w-full pl-0 lg:pl-64 flex flex-col min-h-screen transition-all duration-300 max-w-[100vw]">
      <header class="h-16 flex items-center justify-between px-4 lg:px-8 shrink-0 border-b border-transparent">
        <div class="flex items-center gap-3">
          <button @click="isMobileMenuOpen = true" class="lg:hidden w-8 h-8 flex items-center justify-center text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 transition-colors">
            <Menu class="w-5 h-5" />
          </button>
          <h1 class="text-lg font-medium text-gray-900 dark:text-gray-100 tracking-wide truncate max-w-[150px] sm:max-w-none">{{ currentTitle }}</h1>
        </div>
        <div class="flex items-center gap-2 sm:gap-3">
          <button @click="openGithub" class="w-8 h-8 flex items-center justify-center text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-200 dark:hover:bg-gray-900 transition-colors rounded" title="GitHub">
            <Github class="w-4 h-4" />
          </button>
          <button @click="toggleLanguage" class="w-8 h-8 flex items-center justify-center text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-200 dark:hover:bg-gray-900 transition-colors rounded" title="Change Language">
            <Globe class="w-4 h-4" />
          </button>
          <button @click="toggleTheme" class="w-8 h-8 flex items-center justify-center text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-200 dark:hover:bg-gray-900 transition-colors rounded" title="Toggle Theme">
            <Moon v-if="!isDark" class="w-4 h-4" />
            <Sun v-else class="w-4 h-4" />
          </button>
        </div>
      </header>

      <div class="flex-1 px-4 lg:px-8 pb-12 overflow-x-hidden">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </div>

      <!-- Global Modals -->
      <UserProfileModal :isOpen="showProfileModal" @close="showProfileModal = false" />
    </main>
  </div>
</template>

<style>
::view-transition-old(root),
::view-transition-new(root) {
  animation: none;
  mix-blend-mode: normal;
}
</style>
<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>

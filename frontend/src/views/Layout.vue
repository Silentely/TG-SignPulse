<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { getAppVersion } from '../lib/api'
import {
  LayoutDashboard,
  Users,
  Zap,
  Terminal,
  Settings,
  UserCircle,
  Github,
  Globe,
  Moon,
  Sun,
  Menu,
  X,
} from 'lucide-vue-next'
import { useTheme } from '../composables/useTheme'
import { useI18n } from '../composables/useI18n'
import { lockBodyScroll, unlockBodyScroll } from '../lib/body-scroll-lock'
import UserProfileModal from '../components/settings/UserProfileModal.vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { isDark, toggleTheme } = useTheme()
const { locale, toggleLanguage, t } = useI18n()
const isMobileMenuOpen = ref(false)
const showProfileModal = ref(false)
const sidebarVersion = ref('')

const loadSidebarVersion = async () => {
  const token = authStore.token
  if (!token) return
  try {
    const info = await getAppVersion(token)
    sidebarVersion.value = info.version ? `v${info.version}` : ''
  } catch {
    sidebarVersion.value = ''
  }
}

const goSettingsAbout = () => {
  isMobileMenuOpen.value = false
  router.push({ name: 'settings' })
}

const onKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && isMobileMenuOpen.value) {
    isMobileMenuOpen.value = false
  }
}

let menuScrollLocked = false
watch(isMobileMenuOpen, (open) => {
  if (open) {
    if (!menuScrollLocked) {
      lockBodyScroll()
      menuScrollLocked = true
    }
  } else if (menuScrollLocked) {
    unlockBodyScroll()
    menuScrollLocked = false
  }
})

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  void loadSidebarVersion()
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  if (menuScrollLocked) {
    unlockBodyScroll()
    menuScrollLocked = false
  }
})

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
  window.open('https://github.com/Silentely/TG-SignPulse', '_blank')
}

const handleNavClick = () => {
  isMobileMenuOpen.value = false
}
</script>

<template>
  <div class="flex min-h-screen w-full overflow-x-hidden text-gray-700 dark:text-gray-300 font-sans">
    <!-- 移动端遮罩：点击关闭侧栏 -->
    <div
      v-if="isMobileMenuOpen"
      class="fixed inset-0 bg-gray-900/40 dark:bg-black/60 backdrop-blur-sm z-40 lg:hidden"
      aria-hidden="true"
      @click="isMobileMenuOpen = false"
    />

    <aside 
      class="ui-sidebar fixed inset-y-0 left-0 z-50 flex flex-col transition-transform duration-300 ease-in-out w-64"
      :class="isMobileMenuOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'"
      :aria-hidden="!isMobileMenuOpen && undefined"
    >
      <div class="flex items-center h-14 px-4 border-b border-[var(--sp-border)] gap-2">
        <div class="ui-brand-mark w-7 h-7 text-[11px] shrink-0">TG</div>
        <div class="min-w-0 flex-1">
          <div class="font-mono font-medium tracking-[0.18em] text-gray-900 dark:text-gray-100 text-sm leading-none">SIGNPULSE</div>
          <div class="text-[10px] text-gray-400 mt-1 tracking-wide truncate">
            <button
              v-if="sidebarVersion"
              type="button"
              class="hover:text-sky-500 transition-colors"
              :title="t('settings.aboutTitle')"
              @click="goSettingsAbout"
            >{{ sidebarVersion }}</button>
            <span v-else>Telegram Ops</span>
          </div>
        </div>
        <!-- 仅移动端抽屉显示关闭；提高可点区域与层级 -->
        <button
          type="button"
          class="lg:hidden shrink-0 inline-flex items-center justify-center w-9 h-9 rounded-md text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-100 dark:hover:bg-white/[0.06] relative z-[60]"
          :aria-label="t('common.close')"
          @click.stop="isMobileMenuOpen = false"
        >
          <X class="w-5 h-5" stroke-width="2" />
        </button>
      </div>

      <nav class="flex-1 py-5 flex flex-col gap-1 px-3 overflow-y-auto custom-scrollbar" :aria-label="t('nav.mainNav')">
        <router-link 
          v-for="nav in navigation" 
          :key="nav.id"
          :to="{ name: nav.name }"
          class="flex items-center h-10 px-3 transition-colors whitespace-nowrap rounded-md focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/50"
          :class="route.name === nav.name
            ? 'ui-nav-active'
            : 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-white/[0.03]'"
          :aria-current="route.name === nav.name ? 'page' : undefined"
          @click="handleNavClick"
        >
          <component :is="nav.icon" class="w-[18px] h-[18px] shrink-0 opacity-80" stroke-width="1.5" />
          <span class="ml-3 text-sm font-medium">{{ t(nav.labelKey) }}</span>
        </router-link>
      </nav>

      <div class="border-t border-[var(--sp-border)] p-3">
        <button
          type="button"
          class="flex items-center w-full h-10 px-3 transition-colors whitespace-nowrap rounded-md text-gray-500 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-white/[0.03]"
          @click="showProfileModal = true; isMobileMenuOpen = false"
        >
          <UserCircle class="w-[18px] h-[18px] shrink-0 opacity-80" stroke-width="1.5" />
          <span class="ml-3 text-sm font-medium">{{ t('nav.profile') }}</span>
        </button>
      </div>
    </aside>

    <main class="flex-1 w-full pl-0 lg:pl-64 flex flex-col min-h-screen transition-all duration-300 max-w-[100vw]">
      <header class="ui-header-glass sticky top-0 z-30 h-14 flex items-center justify-between px-4 lg:px-8 shrink-0">
        <div class="flex items-center gap-3 min-w-0">
          <button
            type="button"
            class="ui-icon-btn lg:hidden"
            :aria-label="t('nav.openMenu')"
            :aria-expanded="isMobileMenuOpen"
            @click="isMobileMenuOpen = true"
          >
            <Menu class="w-5 h-5" />
          </button>
          <h1 class="text-base sm:text-lg font-medium text-gray-900 dark:text-gray-100 tracking-wide truncate">
            {{ currentTitle }}
          </h1>
        </div>
        <div class="flex items-center gap-1 sm:gap-1.5">
          <button
            type="button"
            class="ui-icon-btn"
            :title="t('common.github')"
            :aria-label="t('common.github')"
            @click="openGithub"
          >
            <Github class="w-4 h-4" />
          </button>
          <button
            type="button"
            class="ui-icon-btn"
            :title="locale === 'zh' ? 'English' : '中文'"
            :aria-label="t('common.changeLanguage')"
            @click="toggleLanguage"
          >
            <Globe class="w-4 h-4" />
          </button>
          <button
            type="button"
            class="ui-icon-btn"
            :title="isDark ? t('common.lightMode') : t('common.darkMode')"
            :aria-label="isDark ? t('common.lightMode') : t('common.darkMode')"
            @click="toggleTheme($event)"
          >
            <Moon v-if="!isDark" class="w-4 h-4" />
            <Sun v-else class="w-4 h-4" />
          </button>
        </div>
      </header>

      <!-- 避免 overflow-x-hidden 破坏子元素 sticky；用 clip 裁切即可 -->
      <div class="flex-1 px-4 lg:px-8 py-6 pb-12 overflow-x-clip">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </div>

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
  transition: opacity 0.2s ease, transform 0.2s cubic-bezier(0.22, 1, 0.36, 1);
}
.fade-enter-from {
  opacity: 0;
  transform: translateY(6px);
}
.fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
@media (prefers-reduced-motion: reduce) {
  .fade-enter-active,
  .fade-leave-active {
    transition: opacity 0.01ms;
  }
  .fade-enter-from,
  .fade-leave-to {
    transform: none;
  }
}
</style>

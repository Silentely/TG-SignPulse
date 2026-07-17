<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  LayoutDashboard,
  Users,
  Zap,
  Terminal,
  Settings,
  UserCircle,
  Moon,
  Sun,
  Globe,
  Github,
  Search,
  CornerDownLeft,
} from 'lucide-vue-next'
import { useCommandPalette } from '../composables/useCommandPalette'
import { useTheme } from '../composables/useTheme'
import { useI18n } from '../composables/useI18n'
import { lockBodyScroll, unlockBodyScroll } from '../lib/body-scroll-lock'

const router = useRouter()
const { isOpen, search, hide, show } = useCommandPalette()
const { isDark, toggleTheme } = useTheme()
const { locale, toggleLanguage, t } = useI18n()

const inputRef = ref<HTMLInputElement | null>(null)
const activeIndex = ref(0)

type CmdItem = {
  id: string
  label: string
  hint?: string
  group: string
  icon: unknown
  run: () => void
}

const commands = computed<CmdItem[]>(() => [
  {
    id: 'nav-dashboard',
    label: t('nav.dashboard'),
    group: t('command.groupNav'),
    icon: LayoutDashboard,
    run: () => router.push({ name: 'dashboard' }),
  },
  {
    id: 'nav-accounts',
    label: t('nav.accounts'),
    group: t('command.groupNav'),
    icon: Users,
    run: () => router.push({ name: 'accounts' }),
  },
  {
    id: 'nav-tasks',
    label: t('nav.tasks'),
    group: t('command.groupNav'),
    icon: Zap,
    run: () => router.push({ name: 'tasks' }),
  },
  {
    id: 'nav-logs',
    label: t('nav.logs'),
    group: t('command.groupNav'),
    icon: Terminal,
    run: () => router.push({ name: 'logs' }),
  },
  {
    id: 'nav-settings',
    label: t('nav.settings'),
    group: t('command.groupNav'),
    icon: Settings,
    run: () => router.push({ name: 'settings' }),
  },
  {
    id: 'nav-profile',
    label: t('nav.profile'),
    group: t('command.groupNav'),
    icon: UserCircle,
    run: () => {
      // 通过自定义事件打开个人中心（Layout 监听）
      window.dispatchEvent(new CustomEvent('sp:open-profile'))
    },
  },
  {
    id: 'act-theme',
    label: isDark.value ? t('common.lightMode') : t('common.darkMode'),
    group: t('command.groupAction'),
    icon: isDark.value ? Sun : Moon,
    run: () => toggleTheme(),
  },
  {
    id: 'act-lang',
    label: locale.value === 'zh' ? 'English' : '中文',
    group: t('command.groupAction'),
    icon: Globe,
    run: () => toggleLanguage(),
  },
  {
    id: 'act-github',
    label: t('common.github'),
    group: t('command.groupAction'),
    icon: Github,
    run: () => window.open('https://github.com/Silentely/TG-SignPulse', '_blank'),
  },
])

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return commands.value
  return commands.value.filter(
    (c) =>
      c.label.toLowerCase().includes(q) ||
      c.id.toLowerCase().includes(q) ||
      c.group.toLowerCase().includes(q)
  )
})

const grouped = computed(() => {
  const map = new Map<string, CmdItem[]>()
  for (const item of filtered.value) {
    const list = map.get(item.group) || []
    list.push(item)
    map.set(item.group, list)
  }
  return [...map.entries()]
})

const flatFiltered = computed(() => filtered.value)

const runItem = (item: CmdItem) => {
  hide()
  item.run()
}

const onKeydown = (e: KeyboardEvent) => {
  // ⌘K / Ctrl+K
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    if (isOpen.value) hide()
    else show()
    return
  }

  if (!isOpen.value) return

  if (e.key === 'Escape') {
    e.preventDefault()
    hide()
    return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (!flatFiltered.value.length) return
    activeIndex.value = Math.min(activeIndex.value + 1, flatFiltered.value.length - 1)
    return
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIndex.value = Math.max(activeIndex.value - 1, 0)
    return
  }
  if (e.key === 'Enter') {
    e.preventDefault()
    const item = flatFiltered.value[activeIndex.value]
    if (item) runItem(item)
  }
}

let scrollLocked = false

watch(isOpen, async (v) => {
  activeIndex.value = 0
  if (v) {
    if (!scrollLocked) {
      lockBodyScroll()
      scrollLocked = true
    }
    await nextTick()
    inputRef.value?.focus()
  } else if (scrollLocked) {
    unlockBodyScroll()
    scrollLocked = false
  }
})

watch(search, () => {
  activeIndex.value = 0
})

watch(flatFiltered, (list) => {
  if (activeIndex.value >= list.length) {
    activeIndex.value = Math.max(0, list.length - 1)
  }
})

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  if (scrollLocked) {
    unlockBodyScroll()
    scrollLocked = false
  }
})

const flatIndexOf = (item: CmdItem) =>
  flatFiltered.value.findIndex((x) => x.id === item.id)
</script>

<template>
  <Teleport to="body">
    <Transition name="cmd">
      <div
        v-if="isOpen"
        class="fixed inset-0 z-[180] flex items-start justify-center pt-[12vh] sm:pt-[15vh] px-4"
        role="dialog"
        aria-modal="true"
        :aria-label="t('command.title')"
      >
        <div class="absolute inset-0 bg-gray-900/45 dark:bg-black/65 backdrop-blur-[2px]" @click="hide" />

        <div class="relative w-full max-w-lg ui-card shadow-[var(--sp-shadow-md)] overflow-hidden flex flex-col max-h-[min(70vh,520px)]">
          <div class="flex items-center gap-2 px-3 h-12 border-b border-[var(--sp-border)]">
            <Search class="w-4 h-4 text-gray-400 shrink-0" />
            <input
              ref="inputRef"
              v-model="search"
              type="text"
              class="flex-1 bg-transparent outline-none text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400"
              :placeholder="t('command.placeholder')"
              autocomplete="off"
              spellcheck="false"
            >
            <kbd class="hidden sm:inline text-[10px] font-mono text-gray-400 border border-gray-200 dark:border-gray-700 px-1.5 py-0.5">esc</kbd>
          </div>

          <div class="overflow-y-auto flex-1 py-1 custom-scrollbar">
            <div v-if="flatFiltered.length === 0" class="px-4 py-8 text-center text-sm text-gray-400">
              {{ t('command.empty') }}
            </div>

            <template v-for="[group, items] in grouped" :key="group">
              <div class="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-400">
                {{ group }}
              </div>
              <button
                v-for="item in items"
                :key="item.id"
                type="button"
                class="w-full flex items-center gap-3 px-3 py-2.5 text-left text-sm transition-colors"
                :class="flatIndexOf(item) === activeIndex
                  ? 'bg-sky-50 dark:bg-sky-950/40 text-gray-900 dark:text-gray-100'
                  : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/[0.04]'"
                @click="runItem(item)"
                @mouseenter="activeIndex = flatIndexOf(item)"
              >
                <component :is="item.icon" class="w-4 h-4 shrink-0 opacity-70" stroke-width="1.75" />
                <span class="flex-1 truncate">{{ item.label }}</span>
                <CornerDownLeft
                  v-if="flatIndexOf(item) === activeIndex"
                  class="w-3.5 h-3.5 text-gray-400 shrink-0"
                />
              </button>
            </template>
          </div>

          <div class="flex items-center gap-3 px-3 py-2 border-t border-[var(--sp-border)] text-[10px] text-gray-400">
            <span>↑↓ {{ t('command.navigate') }}</span>
            <span>↵ {{ t('command.select') }}</span>
            <span class="ml-auto font-mono">⌘K</span>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.cmd-enter-active,
.cmd-leave-active {
  transition: opacity 0.15s ease;
}
.cmd-enter-active > div:last-child,
.cmd-leave-active > div:last-child {
  transition: transform 0.15s ease, opacity 0.15s ease;
}
.cmd-enter-from,
.cmd-leave-to {
  opacity: 0;
}
.cmd-enter-from > div:last-child,
.cmd-leave-to > div:last-child {
  transform: translateY(-8px) scale(0.98);
  opacity: 0;
}
</style>

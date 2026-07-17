import { ref, computed } from 'vue'

const open = ref(false)
const query = ref('')

export function useCommandPalette() {
  const isOpen = computed(() => open.value)
  const search = computed({
    get: () => query.value,
    set: (v: string) => {
      query.value = v
    },
  })

  const show = () => {
    open.value = true
    query.value = ''
  }

  const hide = () => {
    open.value = false
    query.value = ''
  }

  const toggle = () => {
    if (open.value) hide()
    else show()
  }

  return { isOpen, search, show, hide, toggle, open, query }
}

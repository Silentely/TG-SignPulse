import { createPinia, setActivePinia } from 'pinia'

/**
 * Node.js 22+ 会注入不完整的全局 localStorage（需 --localstorage-file），
 * 会覆盖 jsdom 提供的实现。测试环境统一使用内存 polyfill。
 */
function createMemoryStorage(): Storage {
  const store = new Map<string, string>()
  return {
    get length() {
      return store.size
    },
    clear() {
      store.clear()
    },
    getItem(key: string) {
      return store.has(key) ? store.get(key)! : null
    },
    key(index: number) {
      return Array.from(store.keys())[index] ?? null
    },
    removeItem(key: string) {
      store.delete(key)
    },
    setItem(key: string, value: string) {
      store.set(String(key), String(value))
    },
  }
}

const memoryStorage = createMemoryStorage()
vi.stubGlobal('localStorage', memoryStorage)
if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'localStorage', {
    value: memoryStorage,
    writable: true,
    configurable: true,
  })
}

// 每个测试用例前初始化 Pinia
beforeEach(() => {
  memoryStorage.clear()
  setActivePinia(createPinia())
})

// 全局 mock fetch
const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

// 清理 DOM
afterEach(() => {
  document.body.innerHTML = ''
  vi.clearAllMocks()
})

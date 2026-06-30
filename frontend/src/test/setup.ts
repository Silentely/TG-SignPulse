import { createPinia, setActivePinia } from 'pinia'

// 每个测试用例前初始化 Pinia
beforeEach(() => {
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

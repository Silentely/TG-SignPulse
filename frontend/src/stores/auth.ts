import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { storageGet, storageRemove, storageSet } from '../lib/safe-storage'

const TOKEN_KEY = 'tg-signer-token'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(storageGet(TOKEN_KEY))

  const isAuthenticated = computed(() => !!token.value)

  function setToken(newToken: string) {
    token.value = newToken
    storageSet(TOKEN_KEY, newToken)
  }

  function clearToken() {
    token.value = null
    storageRemove(TOKEN_KEY)
  }

  function logout() {
    clearToken()
    window.location.href = '/'
  }

  // Check token expiry (client-side only, server validates on each request)
  function isTokenExpired(): boolean {
    if (!token.value) return true
    try {
      const payload = JSON.parse(atob(token.value.split('.')[1]))
      return payload.exp && payload.exp * 1000 < Date.now()
    } catch {
      return false
    }
  }

  return { token, isAuthenticated, setToken, clearToken, logout, isTokenExpired }
})

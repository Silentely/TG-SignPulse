import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

const TOKEN_KEY = 'tg-signer-token'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))

  const isAuthenticated = computed(() => !!token.value)

  function setToken(newToken: string) {
    token.value = newToken
    localStorage.setItem(TOKEN_KEY, newToken)
  }

  function clearToken() {
    token.value = null
    localStorage.removeItem(TOKEN_KEY)
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

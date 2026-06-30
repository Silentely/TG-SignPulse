import { createRouter, createWebHistory } from 'vue-router'
import Layout from '../views/Layout.vue'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: Layout,
      redirect: '/dashboard',
      children: [
        { path: 'dashboard', name: 'dashboard', component: () => import('../views/Dashboard.vue') },
        { path: 'accounts', name: 'accounts', component: () => import('../views/Accounts.vue') },
        { path: 'tasks', name: 'tasks', component: () => import('../views/Tasks.vue') },
        { path: 'logs', name: 'logs', component: () => import('../views/Logs.vue') },
        { path: 'settings', name: 'settings', component: () => import('../views/Settings.vue') }
      ]
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/Login.vue')
    }
  ]
})

router.beforeEach((to) => {
  const authStore = useAuthStore()
  if (to.name !== 'login' && !authStore.token) {
    return { name: 'login' }
  } else if (to.name === 'login' && authStore.token) {
    if (authStore.isTokenExpired()) {
      authStore.clearToken()
      return { name: 'login' }
    }
    return { name: 'dashboard' }
  }
})

export default router

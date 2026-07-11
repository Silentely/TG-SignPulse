import { createRouter, createWebHistory } from 'vue-router'
import Layout from '../views/Layout.vue'
import { useAuthStore } from '../stores/auth'
import { resolveAuthRedirect } from '../lib/auth-guard'

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
  return resolveAuthRedirect(typeof to.name === 'string' ? to.name : null, authStore)
})

export default router

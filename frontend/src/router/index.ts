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
        { path: 'plugins', name: 'plugins', component: () => import('../views/Plugins.vue') },
        { path: 'logs', name: 'logs', component: () => import('../views/Logs.vue') },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('../views/Settings.vue'),
          beforeEnter: (to) => {
            const tab = to.query.tab
            const isPluginsTab = Array.isArray(tab) ? tab.includes('plugins') : tab === 'plugins'
            // 兼容旧版书签或外部链接: /settings?tab=plugins 或带 testPlugin 参数，重定向到独立的 /plugins，并剥离仅用于旧页面的 tab 参数
            if (isPluginsTab || to.query.testPlugin) {
              const { tab: _tab, ...restQuery } = to.query
              return { name: 'plugins', query: restQuery, replace: true }
            }
          }
        }
      ]
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/Login.vue')
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('../views/NotFound.vue')
    }
  ]
})

router.beforeEach((to) => {
  const authStore = useAuthStore()
  return resolveAuthRedirect(typeof to.name === 'string' ? to.name : null, authStore)
})

export default router

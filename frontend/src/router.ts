import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from './stores/auth'

// Legacy URL patterns: /base-path/task/:id or /base-path/milestone/:id
// These are redirected to the slide-over ?panels= format for backwards compat.
const LEGACY_TASK_RE = /^(\/[^?#]+)\/task\/([^/?#]+)/
const LEGACY_MILESTONE_RE = /^(\/[^?#]+)\/milestone\/([^/?#]+)/

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('./views/LoginView.vue') },
    { path: '/register', name: 'register', component: () => import('./views/RegisterView.vue') },
    { path: '/settings', name: 'settings', component: () => import('./views/SettingsView.vue') },
    { path: '/admin', name: 'admin', component: () => import('./views/AdminView.vue') },
    { path: '/calendar', name: 'calendar', component: () => import('./views/CalendarView.vue') },
    { path: '/dashboard', name: 'dashboard', component: () => import('./views/DashboardView.vue') },
    {
      path: '/plan/day/:date?',
      name: 'day',
      component: () => import('./views/PlanView.vue'),
      props: route => ({ view: 'day', date: route.params.date }),
    },
    {
      path: '/plan/week/:date?',
      name: 'week',
      component: () => import('./views/PlanView.vue'),
      props: route => ({ view: 'week', date: route.params.date }),
    },
    {
      path: '/plan/month/:date?',
      name: 'month',
      component: () => import('./views/PlanView.vue'),
      props: route => ({ view: 'month', date: route.params.date }),
    },
    { path: '/context', name: 'context', component: () => import('./components/ContextEditor.vue') },
    { path: '/anchors', name: 'anchors', component: () => import('./views/AnchorsView.vue') },
    { path: '/kanban', name: 'kanban', component: () => import('./views/KanbanView.vue') },
    { path: '/', redirect: '/dashboard' },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})

router.beforeEach(async (to) => {
  // ── Legacy URL redirect ──────────────────────────────────────────────────
  // Old routes embedded task/milestone IDs in the path. Convert them to the
  // slide-over ?panels= format so shared links remain functional.
  const path = to.path
  const taskMatch = LEGACY_TASK_RE.exec(path)
  if (taskMatch) {
    return { path: taskMatch[1], query: { ...to.query, panels: `task:${taskMatch[2]}` }, replace: true }
  }
  const milestoneMatch = LEGACY_MILESTONE_RE.exec(path)
  if (milestoneMatch) {
    return { path: milestoneMatch[1], query: { ...to.query, panels: `milestone:${milestoneMatch[2]}` }, replace: true }
  }

  // ── Auth guard ────────────────────────────────────────────────────────────
  const auth = useAuthStore()
  if (!auth.checked) await auth.checkAuth()
  const publicRoutes = ['login', 'register']
  if (!auth.isAuthenticated && !publicRoutes.includes(to.name as string)) {
    return { name: 'login' }
  }
  if (auth.isAuthenticated && publicRoutes.includes(to.name as string)) {
    return { name: 'dashboard' }
  }
  if (to.name === 'admin' && !auth.user?.is_admin) {
    return { name: 'dashboard' }
  }
})

export default router

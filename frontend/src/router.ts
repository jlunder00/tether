import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from './stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('./views/LoginView.vue') },
    { path: '/register', name: 'register', component: () => import('./views/RegisterView.vue') },
    { path: '/settings', name: 'settings', component: () => import('./views/SettingsView.vue') },
    { path: '/admin', name: 'admin', component: () => import('./views/AdminView.vue') },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('./views/DashboardView.vue'),
      children: [
        { path: 'task/:taskId', name: 'dashboard-task', component: () => import('./components/TaskDetailPanel.vue'), props: true },
        { path: 'milestone/:milestoneId', name: 'dashboard-milestone', component: () => import('./components/MilestoneDetailPanel.vue'), props: true },
      ],
    },
    {
      path: '/plan/day/:date?',
      name: 'day',
      component: () => import('./views/PlanView.vue'),
      props: route => ({ view: 'day', date: route.params.date }),
      children: [
        { path: 'task/:taskId', name: 'day-task', component: () => import('./components/TaskDetailPanel.vue'), props: true },
        { path: 'milestone/:milestoneId', name: 'day-milestone', component: () => import('./components/MilestoneDetailPanel.vue'), props: true },
      ],
    },
    {
      path: '/plan/week/:date?',
      name: 'week',
      component: () => import('./views/PlanView.vue'),
      props: route => ({ view: 'week', date: route.params.date }),
      children: [
        { path: 'task/:taskId', name: 'week-task', component: () => import('./components/TaskDetailPanel.vue'), props: true },
        { path: 'milestone/:milestoneId', name: 'week-milestone', component: () => import('./components/MilestoneDetailPanel.vue'), props: true },
      ],
    },
    {
      path: '/plan/month/:date?',
      name: 'month',
      component: () => import('./views/PlanView.vue'),
      props: route => ({ view: 'month', date: route.params.date }),
      children: [
        { path: 'task/:taskId', name: 'month-task', component: () => import('./components/TaskDetailPanel.vue'), props: true },
        { path: 'milestone/:milestoneId', name: 'month-milestone', component: () => import('./components/MilestoneDetailPanel.vue'), props: true },
      ],
    },
    {
      path: '/context',
      name: 'context',
      component: () => import('./components/ContextEditor.vue'),
      children: [
        { path: 'milestone/:milestoneId', name: 'context-milestone', component: () => import('./components/MilestoneDetailPanel.vue'), props: true },
      ],
    },
    { path: '/anchors', name: 'anchors', component: () => import('./views/AnchorsView.vue') },
    {
      path: '/backlog',
      name: 'backlog',
      component: () => import('./views/BacklogView.vue'),
      children: [
        { path: 'task/:taskId', name: 'backlog-task', component: () => import('./components/TaskDetailPanel.vue'), props: true },
      ],
    },
    { path: '/', redirect: '/dashboard' },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})

router.beforeEach(async (to) => {
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

import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from './stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('./views/LoginView.vue') },
    { path: '/register', name: 'register', component: () => import('./views/RegisterView.vue') },
    { path: '/', name: 'home', component: () => import('./components/DayView.vue') },
    // Catch-all redirect to home for now
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.checked) await auth.checkAuth()
  if (!auth.isAuthenticated && to.name !== 'login' && to.name !== 'register') {
    return { name: 'login' }
  }
  if (auth.isAuthenticated && (to.name === 'login' || to.name === 'register')) {
    return { name: 'home' }
  }
})

export default router

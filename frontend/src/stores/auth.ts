import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<{ user_id: string; username: string; is_admin: boolean } | null>(null)
  const checked = ref(false)
  const isAuthenticated = computed(() => !!user.value)

  async function checkAuth() {
    try {
      const resp = await fetch('/auth/me', { credentials: 'include' })
      if (resp.ok) {
        user.value = await resp.json()
      } else {
        user.value = null
      }
    } catch {
      user.value = null
    }
    checked.value = true
  }

  async function login(login: string, password: string) {
    const resp = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ login, password }),
    })
    if (!resp.ok) throw new Error((await resp.json()).detail || 'Login failed')
    user.value = await resp.json()
  }

  async function register(username: string, email: string, password: string, invite_token?: string) {
    const resp = await fetch('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, email, password, invite_token }),
    })
    if (!resp.ok) throw new Error((await resp.json()).detail || 'Registration failed')
    user.value = await resp.json()
  }

  async function logout() {
    await fetch('/auth/logout', { method: 'POST', credentials: 'include' })
    user.value = null
  }

  function loginWithGithub() {
    window.location.href = '/auth/github'
  }

  function loginWithGoogle() {
    window.location.href = '/auth/google'
  }

  return { user, checked, isAuthenticated, checkAuth, login, register, logout, loginWithGithub, loginWithGoogle }
})

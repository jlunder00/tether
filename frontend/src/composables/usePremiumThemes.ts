/** Fetches server-side premium theme CSS and injects it into the document.
 *  Called on boot when the user is known to be premium. The endpoint does not
 *  exist yet — the call is a no-op until the backend ships it.
 *  Uses cookie-based auth; the optional token param is reserved for future API-key auth. */
export async function loadPremiumThemes(token = ''): Promise<void> {
  const res = await fetch('/api/premium/themes', {
    credentials: 'include',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) return
  const { themes } = await res.json() as { themes: { id: string; name: string; css: string }[] }
  let el = document.getElementById('premium-themes') as HTMLStyleElement | null
  if (!el) {
    el = document.createElement('style')
    el.id = 'premium-themes'
    document.head.appendChild(el)
  }
  el.textContent = themes.map(t => t.css).join('\n')
}

/** Removes the injected premium theme CSS element. Call on logout. */
export function unloadPremiumThemes(): void {
  document.getElementById('premium-themes')?.remove()
}

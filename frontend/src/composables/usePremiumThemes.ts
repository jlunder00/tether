/** Fetches server-side premium theme CSS and injects it into the document.
 *  Called on boot when the user is known to be premium. The endpoint does not
 *  exist yet — the call is a no-op until the backend ships it. */
export async function loadPremiumThemes(token: string): Promise<void> {
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

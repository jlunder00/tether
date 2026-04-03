/**
 * Wrapper around fetch that always includes credentials (JWT cookie).
 * Drop-in replacement: `import { api } from '../lib/api'` then use `api(url, opts)`.
 */
export function api(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return fetch(input, { credentials: 'include', ...init })
}

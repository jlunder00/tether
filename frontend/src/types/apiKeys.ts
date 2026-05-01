export interface ApiKey {
  id: string
  name: string
  key_prefix: string   // e.g. "ttr_xxxx"
  created_at: string   // ISO timestamp
  last_used_at: string | null
  revoked_at: string | null
}

export interface ApiKeyCreated extends ApiKey {
  raw_key: string  // shown once, never returned again
}

export interface Connection {
  id: number
  /** Canonical lesser UUID — backend ordering, not displayed directly */
  user_a: string
  /** Canonical greater UUID — backend ordering, not displayed directly */
  user_b: string
  status: 'pending' | 'accepted' | 'blocked'
  /** UUID of whoever sent the request; use to determine incoming vs outgoing direction */
  initiated_by: string
  /** Only semantically meaningful when status === 'accepted' */
  auto_schedule: boolean
  created_at: string
  updated_at: string
  /** Backend-computed: always the other party's UUID regardless of user_a/user_b ordering */
  other_user_id: string
  /** Backend-computed: the other party's username (for display and API calls that require usernames) */
  other_username: string
}

/** Partial shape returned by POST /connections/{id}/accept */
export interface ConnectionStatusPatch {
  id: number
  status: Connection['status']
}

/** Returned by POST /connections/{id}/decline when block=false (row deleted) */
export interface ConnectionDeletedPatch {
  id: number
  deleted: true
}

/** Union of the two possible decline response shapes */
export type DeclineResponse = ConnectionStatusPatch | ConnectionDeletedPatch

export function isDeclineDeleted(r: DeclineResponse): r is ConnectionDeletedPatch {
  return (r as ConnectionDeletedPatch).deleted === true
}

const CONNECTION_STATUSES = ['pending', 'accepted', 'blocked'] as const

/** Narrows an unknown string to a valid Connection status; throws on unrecognised values. */
export function assertConnectionStatus(v: string): Connection['status'] {
  if ((CONNECTION_STATUSES as readonly string[]).includes(v)) {
    return v as Connection['status']
  }
  throw new Error(`Unexpected connection status from server: "${v}"`)
}

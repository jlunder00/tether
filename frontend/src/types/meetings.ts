/** Meeting request as returned by GET /api/meetings and POST /api/meetings/request */
export interface MeetingRequest {
  id: number
  initiator_id: string
  target_ids: string[]
  duration_minutes: number
  context: string | null
  status: MeetingStatus
  round: number
  agreed_slot: string | null
  created_at: string
  updated_at: string
}

export type MeetingStatus = 'open' | 'agreed' | 'cancelled'

/** Body for POST /api/meetings/request */
export interface MeetingRequestBody {
  target_usernames: string[]
  duration_minutes: number
  slots: string[]
  context?: string
}

/** Response from POST /api/meetings/request */
export interface MeetingRequestResponse {
  id: number
  status: MeetingStatus
  round: number
}

/** Response from POST /api/meetings/{id}/cancel */
export interface MeetingCancelResponse {
  id: number
  status: MeetingStatus
}

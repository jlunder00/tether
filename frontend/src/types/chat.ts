export type ChatRole = 'user' | 'bot' | 'system'

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  ts: number     // epoch ms
  actions?: Array<{ action: string; tool?: string }>
}

export interface PermissionDetail {
  label: string
  value: string
}

export interface PermissionRequest {
  request_id: string
  summary: string
  details: PermissionDetail[]
}

export type WsIncomingEvent =
  | { type: 'agent_text_delta'; session_id: string; delta: string }
  | { type: 'agent_action'; session_id: string; action: string; tool?: string }
  | { type: 'permission_request'; session_id: string; request_id: string; summary: string; details: PermissionDetail[] }
  | { type: 'status'; session_id: string; message: string }
  | { type: 'turn_complete'; session_id: string; final_text: string; tokens_used?: number }
  | { type: 'session_ended'; session_id: string }
  | { type: 'trial_usage_update'; session_id: string; remaining: number }

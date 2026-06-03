export type ChatRole = 'user' | 'bot' | 'system'

// Beacon-driven priority for system messages (§3.2 of beacon-notification-system spec).
// Distinct from ConversationDetail.priority (4-level conversation ranking).
// Only rendered on system role messages — ignored on user/bot.
export type SystemMessagePriority = 'normal' | 'important' | 'urgent'

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  ts: number     // epoch ms
  actions?: Array<{ friendly_text: string; tool_name?: string }>
  // Optional: Beacon-assigned priority for system messages. Absent = 'normal'.
  priority?: SystemMessagePriority
}

// permission_request event schema (v2 — Stream B)
export type PermissionKind = 'read_out_of_scope' | 'user_section_edit' | 'destructive'

export interface PermissionRequest {
  request_id: string
  kind: PermissionKind
  target: string
  reason_from_bot: string | null
}

// Status phase enum (v2 — Stream B)
export type StatusPhase = 'classifier' | 'main_reasoning' | 'tool_call' | 'summarization'

// AgentAction status lifecycle (v2 — Stream B)
export type AgentActionStatus = 'starting' | 'running' | 'complete'

export type WsIncomingEvent =
  | { type: 'agent_text_delta'; session_id: string; delta: string }
  | { type: 'agent_action'; session_id: string; id: string; tool_name: string; friendly_text: string; status: AgentActionStatus }
  | { type: 'permission_request'; session_id: string; request_id: string; kind: PermissionKind; target: string; reason_from_bot: string | null }
  | { type: 'status'; session_id: string; phase: StatusPhase; text: string }
  | { type: 'turn_complete'; session_id: string; final_text: string; tokens_used?: number }
  | { type: 'interrupted'; session_id: string }
  | { type: 'session_ended'; session_id: string }
  | { type: 'trial_usage_update'; session_id: string; remaining: number }

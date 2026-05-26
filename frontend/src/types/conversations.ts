export interface ConversationDetail {
  id: string
  name: string
  type: 'interactive' | 'passive' | 'system'
  priority: 'low' | 'normal' | 'high' | 'urgent'
  // Beacon extends state with 'pending' and 'rejected' (beacon-notification-system §7).
  // pending: Beacon-initiated, awaiting first user reply (shown in pending bin, not main list)
  // rejected: user clicked Discard on a pending conv (hidden by default behind filter toggle)
  state: 'open' | 'closed' | 'pending' | 'rejected'
  context_node_id: string | null
  thread_key: string | null
  is_system: boolean
  created_at: string
  last_message_at: string
  folder_name: string | null  // nullable — null if no context_node_id
}

export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant'
  body: string
  source: 'chat' | 'notification' | 'system'
  channel: 'telegram' | 'web' | 'discord' | 'slack'
  created_at: string
}

export interface MessagesPage {
  messages: ConversationMessage[]
  has_more: boolean
}

export type ConversationPriority = ConversationDetail['priority']
export type ConversationState = ConversationDetail['state']

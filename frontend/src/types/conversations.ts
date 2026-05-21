export interface ConversationDetail {
  id: string
  name: string
  type: 'interactive' | 'passive' | 'system'
  priority: 'low' | 'normal' | 'high' | 'urgent'
  state: 'open' | 'closed'
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

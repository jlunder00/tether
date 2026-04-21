export type ChatRole = 'user' | 'bot' | 'system'

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  ts: number     // epoch ms
  streaming?: boolean
}

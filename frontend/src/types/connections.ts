export interface Connection {
  id: number
  user_a: string
  user_b: string
  status: 'pending' | 'accepted' | 'blocked'
  initiated_by: string
  auto_schedule: boolean
  created_at: string
  updated_at: string
  other_user_id: string
}

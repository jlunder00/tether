export interface RruleState {
  freq: 'none' | 'daily' | 'weekly' | 'monthly' | 'yearly' | 'custom'
  interval: number
  byday: string[]
  monthlyMode: 'date' | 'byday'
  nthWeekday: number
  endMode: 'never' | 'count' | 'until'
  count: number
  until: string
}

export const DOW_CODES = ['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'] as const
export const DOW_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

export function parseRrule(rrule: string | null): RruleState {
  const defaults: RruleState = {
    freq: 'none', interval: 1, byday: [], monthlyMode: 'date',
    nthWeekday: 1, endMode: 'never', count: 1, until: '',
  }
  if (!rrule) return defaults

  const parts = Object.fromEntries(rrule.split(';').map(p => p.split('=')))
  const freqStr = (parts['FREQ'] ?? '').toLowerCase()
  const interval = parts['INTERVAL'] ? parseInt(parts['INTERVAL']) : 1
  const countVal = parts['COUNT'] ? parseInt(parts['COUNT']) : 1
  const untilVal = parts['UNTIL'] ?? ''

  let endMode: RruleState['endMode'] = 'never'
  let until = ''
  if (parts['COUNT']) endMode = 'count'
  else if (parts['UNTIL']) {
    endMode = 'until'
    const u = untilVal.replace(/T.*/, '')
    until = `${u.slice(0, 4)}-${u.slice(4, 6)}-${u.slice(6, 8)}`
  }

  let byday: string[] = []
  let monthlyMode: RruleState['monthlyMode'] = 'date'
  let nthWeekday = 1
  if (parts['BYDAY']) {
    const raw = parts['BYDAY']
    const nthMatch = raw.match(/^(-?\d)(SU|MO|TU|WE|TH|FR|SA)$/)
    if (nthMatch) {
      monthlyMode = 'byday'
      nthWeekday = parseInt(nthMatch[1])
      byday = [nthMatch[2]]
    } else {
      byday = raw.split(',')
    }
  }

  const validFreq: RruleState['freq'][] = ['none', 'daily', 'weekly', 'monthly', 'yearly', 'custom']
  const freq = (validFreq.includes(freqStr as RruleState['freq']) ? freqStr : 'custom') as RruleState['freq']

  return { freq, interval, byday, monthlyMode, nthWeekday, endMode, count: countVal, until }
}

export function buildRrule(s: RruleState): string | null {
  if (s.freq === 'none' || s.freq === 'custom') return null

  const parts: string[] = [`FREQ=${s.freq.toUpperCase()}`]
  if (s.interval > 1) parts.push(`INTERVAL=${s.interval}`)

  if (s.freq === 'weekly' && s.byday.length > 0) {
    parts.push(`BYDAY=${s.byday.join(',')}`)
  } else if (s.freq === 'monthly' && s.monthlyMode === 'byday' && s.byday.length > 0) {
    parts.push(`BYDAY=${s.nthWeekday}${s.byday[0]}`)
  }

  if (s.endMode === 'count' && s.count > 1) {
    parts.push(`COUNT=${s.count}`)
  } else if (s.endMode === 'until' && s.until) {
    const d = s.until.replace(/-/g, '')
    parts.push(`UNTIL=${d}T000000Z`)
  }

  return parts.join(';')
}

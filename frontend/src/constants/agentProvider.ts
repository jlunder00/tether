/**
 * Agent provider constants shared between the picker store and settings.
 *
 * LEAKY_PROVIDERS — providers where premium 2.5 is unavailable because their
 * dashboards expose prompt/response content, leaking proprietary intelligence
 * design. Matches the backend's interactive_agent_layer config.
 */
export const LEAKY_PROVIDERS = ['openrouter', 'openai'] as const
export type LeakyProvider = (typeof LEAKY_PROVIDERS)[number]

export const DEFAULT_PROVIDER = 'anthropic_oauth'

export function isLeakyProvider(provider: string): boolean {
  return (LEAKY_PROVIDERS as readonly string[]).includes(provider)
}

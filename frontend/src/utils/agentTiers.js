// Display names for agent tiers, shown to users. The backend identifier
// (pack_name, e.g. "Agent 1") is unchanged — this is a display-only mapping.
export const AGENT_TIER_DISPLAY_NAMES = { 1: 'Trial', 2: 'Start', 3: 'Build', 4: 'Growth' }

export function tierDisplayName(tier) {
  return AGENT_TIER_DISPLAY_NAMES[tier] || `Agent ${tier}`
}

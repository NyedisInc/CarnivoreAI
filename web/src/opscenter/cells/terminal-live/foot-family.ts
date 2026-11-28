
export const STATS_FAMILIES: readonly string[] = ['claude', 'codex'];

export const PROBE_FAMILIES: readonly string[] = ['custom'];

export const SHELL_FAMILY = 'shell';

export type FootKind = 'stats' | 'shell' | 'probe' | 'none';

export function footKindFor(family: string | null | undefined): FootKind {
  const name = (family ?? '').trim().toLowerCase();
  if (!name || name === 'unknown') return 'stats';
  if (name === SHELL_FAMILY) return 'shell';
  if (PROBE_FAMILIES.includes(name)) return 'probe';
  return STATS_FAMILIES.includes(name) ? 'stats' : 'none';
}

export function footMarkPreset(
  family: string | null | undefined,
  usageFamily: string | null | undefined = null,
): 'anthropic' | 'openai' | 'gemini' | null {
  if (usageFamily === 'agy') return 'gemini';
  const name = (family ?? '').trim().toLowerCase();
  if (name === 'claude') return 'anthropic';
  if (name === 'codex') return 'openai';
  return null;
}


export const STATS_FAMILIES: readonly string[] = ['claude', 'codex'];

export const SHELL_FAMILY = 'shell';

export type FootKind = 'stats' | 'shell' | 'none';

export function footKindFor(family: string | null | undefined): FootKind {
  const name = (family ?? '').trim().toLowerCase();
  if (!name || name === 'unknown') return 'stats';
  if (name === SHELL_FAMILY) return 'shell';
  return STATS_FAMILIES.includes(name) ? 'stats' : 'none';
}

export function footMarkPreset(family: string | null | undefined): 'anthropic' | 'openai' | null {
  const name = (family ?? '').trim().toLowerCase();
  if (name === 'claude') return 'anthropic';
  if (name === 'codex') return 'openai';
  return null;
}

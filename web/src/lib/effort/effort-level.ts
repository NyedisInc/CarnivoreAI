
export const EFFORT_LEVELS = ['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'] as const;

export type EffortLevel = (typeof EFFORT_LEVELS)[number];

export function effortLevel(effort: unknown): EffortLevel | null {
  if (typeof effort !== 'string') return null;
  const norm = effort.trim().toLowerCase();
  return (EFFORT_LEVELS as readonly string[]).includes(norm) ? (norm as EffortLevel) : null;
}

export function effortClass(effort: unknown): string {
  const norm = effortLevel(effort);
  return norm ? `effort-level effort--${norm}` : '';
}

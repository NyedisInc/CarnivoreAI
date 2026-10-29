import type { AttentionRow } from './rows';

export function badgeOf(rows: readonly Pick<AttentionRow, 'severity'>[]): { count: number; severity: 'error' | 'warn' | null } {
  const counted = rows.filter((row) => row.severity !== 'info');
  const error = counted.some((row) => row.severity === 'error');
  return { count: counted.length, severity: counted.length === 0 ? null : error ? 'error' : 'warn' };
}

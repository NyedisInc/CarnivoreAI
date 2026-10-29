import type { ListingRow } from '../../sdk';

interface Summary {
  inner: string;
  bucket: string;
}

const BUCKET_STATE: Readonly<Record<string, string>> = {
  permission: 'question',
  working: 'working',
  unread: 'finished_unread',
  done: 'idle',
  dead: 'dead',
};

export function rollupState(rows: readonly ListingRow[]): string | null {
  const fold = (globalThis as { SessionStatusSummary?: { summarizeStates?: (r: readonly unknown[]) => Summary } }).SessionStatusSummary?.summarizeStates;
  if (!fold || rows.length === 0) return null;
  const s = fold(rows);
  if (s.bucket === 'input') return s.inner === 'notice' ? 'notice' : 'startup_gate';
  return BUCKET_STATE[s.bucket] ?? null;
}

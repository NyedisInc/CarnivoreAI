import type { SessionInfo } from './types';

export const WOKEN_HOLD_MS = 120_000;
export const WOKEN_READ_GAP_MS = 1_000;
export const WOKEN_READ_DEADLINE_MS = 30_000;

const held = new Map<number, { row: SessionInfo; at: number }>();

function rowKey(row: SessionInfo): number | null {
  const id = row.session_row_id;
  return typeof id === 'number' && Number.isFinite(id) ? id : null;
}

export function holdWoken(row: SessionInfo, now: number = Date.now()): void {
  const key = rowKey(row);
  if (key === null) return;
  held.set(key, { row, at: now });
}

export function mergeWoken(rows: SessionInfo[], now: number = Date.now()): SessionInfo[] {
  const seen = new Set<number>();
  for (const row of rows) {
    const key = rowKey(row);
    if (key !== null) seen.add(key);
  }
  for (const [key, entry] of [...held]) {
    if (seen.has(key) || now - entry.at > WOKEN_HOLD_MS) held.delete(key);
  }
  return [...rows, ...[...held.values()].map((entry) => structuredClone(entry.row))];
}

export type WokenKey = number | string;

export function findRow(rows: readonly SessionInfo[] | null, key: WokenKey): SessionInfo | null {
  const field = typeof key === 'number' ? 'session_row_id' : 'session_uuid';
  return rows?.find((row) => row[field] === key) ?? null;
}

export interface ReachDeps {
  pushed(): SessionInfo[] | null;
  readList(): Promise<SessionInfo[]>;
  sleep(ms: number): Promise<void>;
  now(): number;
}

export async function reachWoken(rowId: WokenKey, deps: ReachDeps): Promise<SessionInfo | null> {
  const stop = deps.now() + WOKEN_READ_DEADLINE_MS;
  while (deps.now() <= stop) {
    const pushed = findRow(deps.pushed(), rowId);
    if (pushed) return pushed;
    try {
      const found = findRow(await deps.readList(), rowId);
      if (found) {
        holdWoken(found, deps.now());
        return found;
      }
    } catch (failure) {
      console.warn('woken: the direct list read failed', { rowId, error: (failure as Error).message });
    }
    await deps.sleep(WOKEN_READ_GAP_MS);
  }
  return null;
}

export function resetWokenForTests(): void {
  held.clear();
}

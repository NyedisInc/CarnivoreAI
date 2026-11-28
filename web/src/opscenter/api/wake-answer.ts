import type { SessionInfo } from './types';
import { reachWokenSession } from './sessions.svelte';

export const WAKE_NOT_ASLEEP = 'session_not_asleep';

function codeOf(error: { code?: unknown; detail?: unknown; body?: unknown }): string {
  const inner = (value: unknown): unknown => (value && typeof value === 'object' ? (value as { code?: unknown }).code : undefined);
  const candidates = [error.code, inner(error.detail), inner((error.body as { detail?: unknown } | null | undefined)?.detail), inner(error.body)];
  const found = candidates.find((value) => typeof value === 'string' && value);
  return typeof found === 'string' ? found : '';
}

export function isNotAsleepRefusal(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false;
  const shaped = error as { status?: unknown; code?: unknown; detail?: unknown; body?: unknown };
  return shaped.status === 409 && codeOf(shaped) === WAKE_NOT_ASLEEP;
}

export async function liveRowAfterNotAsleep(
  error: unknown,
  sessionUuid: string,
  reach: (key: string) => Promise<SessionInfo | null> = reachWokenSession,
): Promise<SessionInfo | null> {
  if (!sessionUuid || !isNotAsleepRefusal(error)) return null;
  return reach(sessionUuid);
}

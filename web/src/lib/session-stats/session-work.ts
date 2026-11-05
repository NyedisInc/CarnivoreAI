import { fetchBackgroundWork, type SessionBackgroundWork } from '../background-work/background-work';
import { fetchSubagents, type SessionSubagents } from '../subagents/subagents';

export const SESSION_WORK_REUSE_MS = 5000;

export interface SessionWorkRead {
  subagents: PromiseSettledResult<SessionSubagents>;
  work: PromiseSettledResult<SessionBackgroundWork>;
}

interface Held {
  key: string;
  at: number;
  read: Promise<SessionWorkRead>;
}

const MAX_HELD = 64;

const held = new Map<string, Held>();

function prune(now: number): void {
  for (const [id, entry] of held) if (now - entry.at >= SESSION_WORK_REUSE_MS) held.delete(id);
  while (held.size > MAX_HELD) held.delete(held.keys().next().value as string);
}

export function readSessionWork(
  sessionId: string,
  key: string,
  options: { force?: boolean; nowMs?: number } = {},
): Promise<SessionWorkRead> {
  const now = options.nowMs ?? Date.now();
  const mine = held.get(sessionId);
  prune(now);
  if (!options.force && mine && mine.key === key && now - mine.at < SESSION_WORK_REUSE_MS) return mine.read;
  const read = Promise.allSettled([fetchSubagents(sessionId), fetchBackgroundWork(sessionId)]).then(
    ([subagents, work]) => ({ subagents, work }),
  );
  held.set(sessionId, { key, at: now, read });
  return read;
}

export function resetSessionWork(): void {
  held.clear();
}

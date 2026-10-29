
import { authFetch } from './auth.svelte';
import { pushedRows, resource, type Resource } from './poll.svelte';
import type { SessionRecord } from './types';

export const ASLEEP_POLL_MS = 5000;

export const asleep: Resource<SessionRecord[]> = resource<SessionRecord[]>(
  async () => pushedRows<SessionRecord>('asleep') ?? authFetch<SessionRecord[]>('/sessions/asleep'),
  { intervalMs: ASLEEP_POLL_MS, name: 'asleep', demo: () => [], pushed: ['asleep'] },
);

/* pick a wrapper */
export const WAKE_WRAPPER_NEEDED = 'wrapper_needed';

export const WAKE_TRANSCRIPT_MISSING = 'transcript_missing';

export interface SleepResult {
  status: 'asleep' | 'refused' | string;
  detail: string;
  session_uuid?: string;
  session_name?: string | null;
  code?: string | null;
}

export async function sleepSession(sessionUuid: string): Promise<SleepResult> {
  return authFetch<SleepResult>(`/sessions/${encodeURIComponent(sessionUuid)}/sleep`, { method: 'POST' });
}

export interface WakeResult {
  status: 'started' | 'refused' | string;
  detail: string;
  code?: string | null;
  wrapper_options?: string[];
}

export async function wakeSession(sessionUuid: string, agentType?: string, startFresh?: boolean): Promise<WakeResult> {
  const init: RequestInit = { method: 'POST' };
  const body: Record<string, unknown> = {};
  if (agentType) body.agent_type = agentType;
  if (startFresh) body.start_fresh = true;
  if (Object.keys(body).length) init.body = JSON.stringify(body);
  return authFetch<WakeResult>(`/sessions/${encodeURIComponent(sessionUuid)}/wake`, init);
}

interface LegacySleep {
  pickAndWake?: (name: string, label: string, sessionUuid: string) => Promise<WakeResult | null>;
  offerFresh?: (name: string, label: string, sessionUuid: string) => Promise<WakeResult | null>;
}

export function wakeOrPick(sessionUuid: string, name: string, label: string): Promise<WakeResult | null> {
  const running = wakesInFlight.get(sessionUuid);
  if (running) return running;
  const run = wakeOrPickOnce(sessionUuid, name, label).finally(() => wakesInFlight.delete(sessionUuid));
  wakesInFlight.set(sessionUuid, run);
  return run;
}

const wakesInFlight = new Map<string, Promise<WakeResult | null>>();

async function wakeOrPickOnce(sessionUuid: string, name: string, label: string): Promise<WakeResult | null> {
  const host = globalThis as { NavigationGeneration?: { begin(t: string): unknown }; WakeFocus?: { afterWake(u: string, n: unknown): unknown } };
  const nav = host.NavigationGeneration ? host.NavigationGeneration.begin(`wake:${name}`) : null;
  let answer = await wakeSession(sessionUuid);
  if (answer.status === 'refused' && answer.code === WAKE_WRAPPER_NEEDED) {
    const legacy = (globalThis as { SessionRowMenuSleep?: LegacySleep }).SessionRowMenuSleep;
    if (legacy && typeof legacy.pickAndWake === 'function') {
      const picked = await legacy.pickAndWake(name, label, sessionUuid);
      if (!picked) return null;
      answer = picked;
    }
  }
  if (answer.status === 'refused' && answer.code === WAKE_TRANSCRIPT_MISSING) {
    const legacy = (globalThis as { SessionRowMenuSleep?: LegacySleep }).SessionRowMenuSleep;
    if (legacy && typeof legacy.offerFresh === 'function') answer = (await legacy.offerFresh(name, label, sessionUuid)) ?? answer;
  }
  if (answer.status === 'started') void host.WakeFocus?.afterWake(sessionUuid, nav);
  return answer;
}

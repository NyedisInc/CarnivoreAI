import { authFetch, familyOf, resourcePush } from '../sdk';

export const PREFS_FAMILY = 'cplug.huddle.prefs';

interface AllPrefs {
  sessions: Record<string, boolean>;
  lists: Record<string, boolean>;
  leads?: Record<string, string>;
  dnd?: string[];
}

const cache: { sessions: Record<string, boolean>; lists: Record<string, boolean>; leads: Record<string, string>; dnd: Set<string>; loaded: boolean } =
  { sessions: {}, lists: {}, leads: {}, dnd: new Set(), loaded: false };
let started = false;

export function effectiveNudge(own: boolean | undefined, projectOn: boolean): boolean {
  return own === undefined ? projectOn : own;
}

export function sessionNudgeOn(sessionUuid: string, projectId: number | string | null | undefined): boolean {
  const projectOn = projectId == null ? false : cache.lists[String(projectId)] !== false;
  return effectiveNudge(cache.sessions[sessionUuid], projectOn);
}

export function sessionNudgeLoaded(): boolean {
  return cache.loaded;
}

export async function refreshSessionNudge(): Promise<void> {
  try {
    const body = await authFetch<AllPrefs>('/cplugs/huddle/session-prefs');
    cache.sessions = body.sessions ?? {};
    cache.lists = body.lists ?? {};
    cache.leads = body.leads ?? {};
    cache.dnd = new Set(body.dnd ?? []);
    cache.loaded = true;
  } catch (err) {
    console.error('[huddle] could not read the nudge switches:', err);
  }
}

export async function setSessionNudge(sessionUuid: string, on: boolean): Promise<boolean> {
  const stored = await authFetch<{ session: string; nudge: boolean | null }>(
    `/cplugs/huddle/sessions/${encodeURIComponent(sessionUuid)}/prefs`, { method: 'PUT', body: JSON.stringify({ nudge: on }) });
  if (stored.nudge === null) delete cache.sessions[sessionUuid];
  else cache.sessions[sessionUuid] = stored.nudge;
  return stored.nudge === true;
}

export function sessionLeads(sessionUuid: string, projectId: number | string | null | undefined): boolean {
  return projectId != null && cache.leads[String(projectId)] === sessionUuid;
}

export function sessionDnd(sessionUuid: string): boolean {
  return cache.dnd.has(sessionUuid);
}

export async function setProjectLead(projectId: number | string, sessionUuid: string | null): Promise<void> {
  const key = String(projectId);
  await authFetch(`/cplugs/huddle/lists/${encodeURIComponent(key)}/lead`, { method: 'PUT', body: JSON.stringify({ session: sessionUuid }) });
  if (sessionUuid === null) delete cache.leads[key];
  else cache.leads[key] = sessionUuid;
}

export async function setSessionDnd(sessionUuid: string, on: boolean): Promise<boolean> {
  const stored = await authFetch<{ session: string; dnd: boolean }>(
    `/cplugs/huddle/sessions/${encodeURIComponent(sessionUuid)}/dnd`, { method: 'PUT', body: JSON.stringify({ dnd: on }) });
  if (stored.dnd) cache.dnd.add(sessionUuid);
  else cache.dnd.delete(sessionUuid);
  return stored.dnd;
}

export function startSessionNudge(): void {
  if (started) return;
  started = true;
  resourcePush().onChange((topics) => {
    if (topics.some((topic) => familyOf(topic) === PREFS_FAMILY)) void refreshSessionNudge();
  });
  void refreshSessionNudge();
}

export function resetSessionNudge(): void {
  cache.sessions = {};
  cache.lists = {};
  cache.leads = {};
  cache.dnd = new Set();
  cache.loaded = false;
  started = false;
}

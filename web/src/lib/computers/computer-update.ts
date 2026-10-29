import type { authFetch } from '../../opscenter/api/auth.svelte';

export interface UpdateStatus {
  attached: boolean;
  state: string;
  current_version: string;
  latest_version: string;
  percent: number | null;
  detail: string | null;
  auto_update: boolean;
}

export type UpdateView =
  | { kind: 'ok'; update: UpdateStatus }
  | { kind: 'unsupported' }
  | { kind: 'refused'; reason: string }
  | { kind: 'unavailable'; reason: string };

export type UpdateAction = 'check' | 'install' | 'auto';

export const KNOWN_STATES = ['not_configured', 'invalid_feed', 'idle', 'checking', 'available', 'downloading', 'ready', 'current', 'unknown', 'error', 'update_refused'];

export function routeFor(hostKey: string): string {
  return hostKey ? `/app-update/computer/${encodeURIComponent(hostKey)}` : '/app-update';
}

export function viewOf(answer: unknown, isPeer: boolean): UpdateView {
  const body = (answer ?? {}) as Record<string, unknown>;
  if (!isPeer) return typeof body.state === 'string' ? { kind: 'ok', update: body as unknown as UpdateStatus } : { kind: 'unavailable', reason: 'bad_answer' };
  const reason = typeof body.reason === 'string' ? body.reason : '';
  if (body.status === 'ok' && body.update) return { kind: 'ok', update: body.update as UpdateStatus };
  if (body.status === 'unsupported') return { kind: 'unsupported' };
  if (body.status === 'refused') return { kind: 'refused', reason };
  return { kind: 'unavailable', reason: reason || 'bad_answer' };
}

export async function runUpdate(fetcher: typeof authFetch, hostKey: string, action?: UpdateAction, enabled?: boolean): Promise<UpdateView> {
  const base = routeFor(hostKey);
  const init = action === 'auto' ? { method: 'PUT', body: JSON.stringify({ enabled }) } : action ? { method: 'POST' } : undefined;
  const path = action === 'auto' ? `${base}/auto-update` : action ? `${base}/${action}` : base;
  try {
    return viewOf(await fetcher<unknown>(path, init), hostKey !== '');
  } catch {
    return { kind: 'unavailable', reason: 'request_failed' };
  }
}

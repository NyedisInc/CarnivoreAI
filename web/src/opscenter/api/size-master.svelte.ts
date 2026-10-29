
import { authFetch } from './auth.svelte';

export interface SizeMasterState {
  session_id: string;
  master: string | null;
  master_attached: boolean;
}

export const SIZE_MASTER_EVENT = 'cloude:size-master';

export const SIZE_MASTER_USER_RELEASE_EVENT = 'cloude:size-master-user-release';

export const sizeMasters: Record<string, string | null> = $state({});

interface SizeMasterModule {
  clientId(): string;
}

export function thisTabId(): string | null {
  const mod = (globalThis as { TerminalSizeMaster?: SizeMasterModule }).TerminalSizeMaster;
  return mod ? mod.clientId() : null;
}

function record(sessionId: string, master: string | null): void {
  if (sessionId) sizeMasters[sessionId] = master;
}

if (typeof window !== 'undefined') {
  window.addEventListener(SIZE_MASTER_EVENT, (event) => {
    const detail = (event as CustomEvent<{ sessionId?: string; master?: string | null }>).detail;
    if (detail?.sessionId) record(detail.sessionId, detail.master ?? null);
  });
}

export async function claimSizeMaster(sessionId: string): Promise<SizeMasterState> {
  const id = thisTabId();
  if (!id) throw new Error('size master: no client id');
  const state = await authFetch<SizeMasterState>(
    `/sessions/${encodeURIComponent(sessionId)}/size-master`,
    { method: 'PUT', body: JSON.stringify({ client_id: id }) },
  );
  record(sessionId, state.master);
  return state;
}

export async function releaseSizeMaster(sessionId: string): Promise<SizeMasterState> {
  const id = thisTabId();
  const query = id ? `?client_id=${encodeURIComponent(id)}` : '';
  const state = await authFetch<SizeMasterState>(
    `/sessions/${encodeURIComponent(sessionId)}/size-master${query}`,
    { method: 'DELETE' },
  );
  record(sessionId, state.master);
  return state;
}

export function sizeMasterRole(sessionId: string): 'none' | 'master' | 'watcher' {
  const holder = sessionId ? sizeMasters[sessionId] ?? null : null;
  return holder === null ? 'none' : holder === thisTabId() ? 'master' : 'watcher';
}

export async function toggleSizeMaster(sessionId: string): Promise<void> {
  if (!sessionId) return;
  try {
    if (sizeMasterRole(sessionId) === 'master') {
      window.dispatchEvent(new CustomEvent(SIZE_MASTER_USER_RELEASE_EVENT, { detail: { sessionId } }));
      await releaseSizeMaster(sessionId);
    }
    else await claimSizeMaster(sessionId);
  } catch (err) {
    console.error('[size-master] size master change failed:', err);
  }
}

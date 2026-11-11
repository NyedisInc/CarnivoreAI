
import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { t } from '../i18n/index.svelte';

export interface GlobalSyncSettings {
  enabled: boolean;
  auto: boolean;
  claude: boolean;
  codex: boolean;
}

export interface GlobalSyncLast {
  state: string;
  at?: number;
  reason?: string;
  sent?: { files?: number; refused_total?: number; refused?: Array<[string, string]> };
}

export interface GlobalSyncComputer {
  install_id: string;
  label: string;
  gate: string | null;
  last: GlobalSyncLast | null;
}

export interface GlobalSyncView {
  settings: GlobalSyncSettings;
  is_main: boolean;
  computers: GlobalSyncComputer[];
}

export const GLOBAL_SYNC_POLL_MS = 15000;

export const globalSync: Resource<GlobalSyncView> = resource<GlobalSyncView>(
  () => authFetch<GlobalSyncView>('/pack/global-sync'),
  { intervalMs: GLOBAL_SYNC_POLL_MS, name: 'pack-global-sync', topics: ['pack_global_sync'] },
);

export const globalSyncActivity = $state<{ busy: boolean; error: string | null }>({ busy: false, error: null });

const GATE_WORDS = ['not_approved', 'receiver_off', 'offline', 'old_version', 'one_way', 'not_main'];

export function gateWord(c: Pick<GlobalSyncComputer, 'gate' | 'last'>): string {
  if (c.gate) return GATE_WORDS.includes(c.gate) ? `pack.globalsync.gate.${c.gate}` : 'pack.globalsync.gate.other';
  const state = c.last?.state;
  return state ? `pack.globalsync.last.${state}` : 'pack.globalsync.last.none';
}

async function write(path: string, method: 'PUT' | 'POST', body: unknown): Promise<void> {
  if (globalSyncActivity.busy) return;
  globalSyncActivity.busy = true;
  globalSyncActivity.error = null;
  try {
    await authFetch(path, { method, body: JSON.stringify(body) });
  } catch (error) {
    globalSyncActivity.error = error instanceof Error && error.message ? error.message : t('pack.machines.error.failed');
  } finally {
    globalSyncActivity.busy = false;
    await globalSync.refresh(true);
  }
}

export function saveGlobalSync(patch: Partial<GlobalSyncSettings>): Promise<void> {
  return write('/pack/global-sync', 'PUT', patch);
}

export function syncNow(installIds: string[] = []): Promise<void> {
  return write('/pack/global-sync/sync', 'POST', { install_ids: installIds });
}

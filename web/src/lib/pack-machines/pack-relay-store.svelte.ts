
import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { fetchLedgerAccounts, type LedgerAccount } from '../byoai/api';
import { t } from '../i18n/index.svelte';

export interface RelayTarget {
  machine: string;
  profile: string | null;
  state: string;
  last_expiry_pushed: number | null;
  last_push_at: number | null;
}

export interface RelayView {
  accounts: Record<string, RelayTarget[]>;
}

export const PACK_RELAY_POLL_MS = 30000;

export const packRelay: Resource<RelayView> = resource<RelayView>(
  () => authFetch<RelayView>('/pack/relay'),
  { intervalMs: PACK_RELAY_POLL_MS, name: 'pack-relay' },
);

export const claudeAccounts: Resource<LedgerAccount[]> = resource<LedgerAccount[]>(
  async () => (await fetchLedgerAccounts()).filter((a) => a.provider === 'claude'),
  { intervalMs: 60000, name: 'pack-relay-accounts' },
);

export const relayActivity = $state<{ busy: string | null; error: string | null }>({ busy: null, error: null });

export async function setRelay(account: string, machines: string[]): Promise<void> {
  if (relayActivity.busy) return;
  relayActivity.busy = account;
  relayActivity.error = null;
  try {
    await authFetch(`/pack/relay/${encodeURIComponent(account)}`, { method: 'PUT', body: JSON.stringify({ machines }) });
  } catch (error) {
    relayActivity.error = error instanceof Error ? error.message : t('pack.machines.error.failed');
  } finally {
    relayActivity.busy = null;
    await packRelay.refresh(true);
  }
}

import { authFetch } from '../../opscenter/api/auth.svelte';
import { packMachines } from '../pack-machines/pack-machines-store.svelte';
import { apiErrorMessageOr } from '../errors/failure-reason';
import { t } from '../i18n/index.svelte';

export const reconnectActivity = $state<{ busy: string | null; error: string | null }>({ busy: null, error: null });

async function write(key: string, send: () => Promise<unknown>): Promise<boolean> {
  if (reconnectActivity.busy) return false;
  reconnectActivity.busy = key;
  reconnectActivity.error = null;
  try {
    await send();
    return true;
  } catch (error) {
    reconnectActivity.error = apiErrorMessageOr(error, t('roster.reconnect.error'));
    return false;
  } finally {
    reconnectActivity.busy = null;
    await packMachines.refresh(true);
  }
}

const put = (path: string, body: unknown): Promise<unknown> => authFetch(path, { method: 'PUT', body: JSON.stringify(body) });

export const setRelay = (on: boolean): Promise<boolean> => write('relay', () => put('/pack/reconnect', { relay: on }));

export const setTakeover = (on: boolean, relayOn: boolean): Promise<boolean> => write('takeover', () => put('/pack/reconnect', { relay: relayOn, takeover: on }));

export const saveOrder = (order: readonly string[]): Promise<boolean> => write('order', () => put('/pack/successors', { order }));

export const setEligible = (machine: string, eligible: boolean): Promise<boolean> => write(`eligible:${machine}`, () => put('/pack/eligible', { machine, eligible }));

export const setLinkPeers = (machine: string, on: boolean): Promise<boolean> => write(`link:${machine}`, () => put('/pack/link-peers', { machine, on }));

export const confirmInterim = (): Promise<boolean> => write('confirm', () => authFetch('/pack/interim/confirm', { method: 'POST' }));

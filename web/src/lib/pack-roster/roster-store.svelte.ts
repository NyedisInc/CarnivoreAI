import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { t } from '../i18n/index.svelte';
import { apiErrorMessageOr } from '../errors/failure-reason';
import { createFederationApi, type DiscoveredMac, type DiscoveredResponse, type PeerRow } from '../hosts-page/federation-api';
import { HOSTS_ROUTE, type HostRow, type HostsListResponse } from '../hosts-page/hosts-adapter';

export const ROSTER_TOPIC = 'pack_roster';
export const ROSTER_POLL_MS = 15000;

export const hosts: Resource<HostsListResponse> = resource<HostsListResponse>(() => authFetch<HostsListResponse>(HOSTS_ROUTE), { intervalMs: ROSTER_POLL_MS, name: 'roster-hosts', topics: [ROSTER_TOPIC] });
const fed = createFederationApi();
export const peers: Resource<readonly PeerRow[]> = resource<readonly PeerRow[]>(() => fed.peers().catch((): readonly PeerRow[] => []), { intervalMs: ROSTER_POLL_MS, name: 'roster-peers', topics: [ROSTER_TOPIC] });
export const discovered: Resource<DiscoveredResponse | null> = resource<DiscoveredResponse | null>(() => fed.discovered().catch(() => null), { intervalMs: ROSTER_POLL_MS, name: 'roster-discovered', topics: [ROSTER_TOPIC] });

export const nearby = (): readonly DiscoveredMac[] => discovered.data?.discovered ?? [];

export const rosterActivity = $state<{ busy: string | null; error: string | null; note: string | null }>({ busy: null, error: null, note: null });

export function reasonOf(error: unknown): string {
  return apiErrorMessageOr(error, t('computers.error.failed'));
}

export async function refreshRoster(): Promise<void> {
  await Promise.all([hosts.refresh(true), peers.refresh(true), discovered.refresh(true)]);
}

async function write<T>(key: string, send: () => Promise<T>): Promise<T | undefined> {
  if (rosterActivity.busy) return undefined;
  rosterActivity.busy = key;
  rosterActivity.error = null;
  try {
    return await send();
  } catch (error) {
    rosterActivity.error = reasonOf(error);
    return undefined;
  } finally {
    rosterActivity.busy = null;
    await refreshRoster();
  }
}

export const probeHost = (key: string): Promise<HostRow | undefined> =>
  write(`probe:${key}`, () => authFetch<HostRow>(`${HOSTS_ROUTE}/${encodeURIComponent(key)}/probe`, { method: 'POST' }));

export const setHostEnabled = (key: string, enabled: boolean): Promise<HostRow | undefined> =>
  write(`enable:${key}`, () => authFetch<HostRow>(`${HOSTS_ROUTE}/${encodeURIComponent(key)}`, { method: 'PATCH', body: JSON.stringify({ enabled }) }));

export async function removeHost(key: string): Promise<boolean> {
  const done = await write(`remove-host:${key}`, () => authFetch<{ deleted: boolean }>(`${HOSTS_ROUTE}/${encodeURIComponent(key)}`, { method: 'DELETE' }));
  return done?.deleted === true;
}

export const linkHost = (key: string, computerInstallId: string | null): Promise<HostRow | undefined> =>
  write(`link:${key}`, () => authFetch<HostRow>(`${HOSTS_ROUTE}/${encodeURIComponent(key)}/computer`, { method: 'PUT', body: JSON.stringify({ computer_install_id: computerInstallId }) }));

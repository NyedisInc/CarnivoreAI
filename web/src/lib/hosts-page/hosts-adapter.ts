import { authFetch } from '../../opscenter/api/auth.svelte';
import type { ManagerAdapter, ManagerItem } from '../manager-frame/types';
import type { Translate } from '../sessions/types';
import { createFederationApi, type DiscoveredMac, type FederationApi, type PeerRow } from './federation-api';

export const HOSTS_ROUTE = '/hosts';

export const LOCAL_HOST_KEY = 'local';

export interface HostRow {
    readonly key: string;
    readonly label: string;
    readonly local: boolean;
    readonly ssh_target: string | null;
    readonly ssh_port: number | null;
    readonly socket: string | null;
    readonly enabled: boolean;
    readonly session_count: number;
    readonly probe_state: string;
    readonly probe_detail: string | null;
    readonly probed_at: string | null;
    readonly tmux_path: string | null;
    readonly tmux_version: string | null;
    readonly login_path: string | null;
    readonly agent_paths: Readonly<Record<string, string>> | null;
    readonly login_shell: string | null;
    readonly machine_id: string | null;
    readonly remote_carnivore: string | null;
    readonly computer_install_id?: string | null;
    readonly created_at: string;
    readonly updated_at: string;
}

export interface HostsListResponse {
    readonly status: 'ok' | 'unavailable';
    readonly detail?: string | null;
    readonly hosts: readonly HostRow[];
}

export type HostKind = 'ssh' | 'peer' | 'found';

export interface HostItem extends ManagerItem {
    readonly kind: HostKind;
    readonly row: HostRow | null;
    readonly peer: PeerRow | null;
    readonly found: DiscoveredMac | null;
    readonly group: string;
}

export const FOUND_GROUP = 'found';

const PEER_STATE_KEYS: Readonly<Record<string, string>> = {
    connecting: 'hosts.peer.state.connecting',
    connected: 'hosts.peer.state.connected',
    disconnected: 'hosts.peer.state.disconnected',
    incompatible: 'hosts.peer.state.incompatible',
    unpaired: 'hosts.peer.state.unpaired',
    identity_changed: 'hosts.peer.state.identity_changed',
};

const PEER_HELP_KEYS: Readonly<Record<string, string>> = {
    connecting: 'hosts.peer.help.connecting',
    connected: 'hosts.peer.help.connected',
    disconnected: 'hosts.peer.help.disconnected',
    incompatible: 'hosts.peer.help.incompatible',
    unpaired: 'hosts.peer.help.unpaired',
    identity_changed: 'hosts.peer.help.identity_changed',
};

export function peerStateHelp(state: string, t: Translate): string {
    const key = PEER_HELP_KEYS[state];
    return key ? t(key) : '';
}

export function peerStateLabel(state: string, t: Translate): string {
    const key = PEER_STATE_KEYS[state];
    return key ? t(key) : state;
}

export function foundStateLabel(state: string, t: Translate): string {
    return state === 'pinned'
        ? t('hosts.found.state.pinned')
        : state === 'identity_changed'
          ? t('hosts.peer.state.identity_changed')
          : t('hosts.found.state.new');
}

export function machineKey(target: string | null | undefined): string {
    const host = (target ?? '').split('@').pop()!.toLowerCase().replace(/\.$/, '');
    return /^[\d.]+$/.test(host) || host.includes(':') ? host : (host.split('.')[0] ?? host);
}

const PROBE_KEYS: Readonly<Record<string, string>> = {
    never: 'hosts.page.probe.never',
    ok: 'hosts.page.probe.ok',
    unreachable: 'hosts.page.probe.unreachable',
    auth_failed: 'hosts.page.probe.auth_failed',
    host_key_unknown: 'hosts.page.probe.host_key_unknown',
    handshake_refused: 'hosts.page.probe.handshake_refused',
    timeout: 'hosts.page.probe.timeout',
};

export function probeVerdict(state: string, t: Translate): string {
    const key = PROBE_KEYS[state];
    return key ? t(key) : t('hosts.page.probe.other', { state });
}

export function toHostItem(row: HostRow, t: Translate): HostItem {
    const marks: string[] = [];
    if (row.local) marks.push(t('hosts.page.mark_local'));
    else marks.push(probeVerdict(row.probe_state, t));
    return {
        id: row.key,
        name: row.label || row.key,
        meta: row.local ? null : row.ssh_target,
        marks,
        enabled: row.local ? null : row.enabled,
        removeBlocked: row.local
            ? t('hosts.remove.blocked.local')
            : row.session_count > 0
                ? t('hosts.remove.blocked.in_use')
                : null,
        kind: 'ssh',
        row,
        peer: null,
        found: null,
        group: 'm:' + (row.local ? 'local' : machineKey(row.ssh_target) || row.key),
    };
}

export function toPeerItem(peer: PeerRow, row: HostRow | null, t: Translate): HostItem {
    return {
        id: peer.key,
        name: peer.label || peer.key,
        meta: null,
        marks: [t('hosts.peer.mark')],
        enabled: null,
        removeBlocked: t('hosts.remove.blocked.peer'),
        kind: 'peer',
        row,
        peer,
        found: null,
        group: 'm:' + (machineKey(row?.ssh_target) || peer.key),
    };
}

export function toFoundItem(found: DiscoveredMac, t: Translate): HostItem {
    return {
        id: `found:${found.name}`,
        name: found.name,
        meta: `${found.host}:${found.port}`,
        marks: [foundStateLabel(found.state, t)],
        enabled: null,
        removeBlocked: t('hosts.remove.blocked.found'),
        kind: 'found',
        row: null,
        peer: null,
        found,
        group: FOUND_GROUP,
    };
}

export function createHostsAdapter(
    t: Translate,
    fetcher: typeof authFetch = authFetch,
    fed: FederationApi = createFederationApi(fetcher),
): ManagerAdapter {
    let peersByKey = new Map<string, PeerRow>();
    const itemFor = (row: HostRow): HostItem => {
        const peer = peersByKey.get(row.key);
        return peer ? toPeerItem(peer, row, t) : toHostItem(row, t);
    };
    return {
        async list(): Promise<readonly ManagerItem[]> {
            const [body, peers, seen] = await Promise.all([
                fetcher<HostsListResponse>(HOSTS_ROUTE),
                fed.peers().catch((): readonly PeerRow[] => []),
                fed.discovered().catch(() => null),
            ]);
            if (body?.status === 'unavailable') {
                throw new Error(body.detail || t('hosts.page.empty'));
            }
            peersByKey = new Map(peers.map((p) => [p.key, p]));
            const rows = body?.hosts ?? [];
            const ssh = rows.filter((row) => !peersByKey.has(row.key)).map((row) => toHostItem(row, t));
            const paired = peers.map((p) => toPeerItem(p, rows.find((r) => r.key === p.key) ?? null, t));
            const fids = new Set(peers.map((p) => p.fid));
            const found = (seen?.discovered ?? []).filter((d) => !fids.has(d.fid)).map((d) => toFoundItem(d, t));
            return [...ssh, ...paired, ...found];
        },
        async setEnabled(id: string, enabled: boolean): Promise<ManagerItem> {
            const row = await fetcher<HostRow>(`${HOSTS_ROUTE}/${encodeURIComponent(id)}`, {
                method: 'PATCH',
                body: JSON.stringify({ enabled }),
            });
            return itemFor(row);
        },
        async remove(id: string): Promise<void> {
            await fetcher<{ key: string; deleted: boolean }>(`${HOSTS_ROUTE}/${encodeURIComponent(id)}`, {
                method: 'DELETE',
            });
        },
    };
}

export interface AddHostPayload {
    label: string;
    ssh_target: string;
    ssh_port?: number | null;
    socket?: string | null;
}

export interface HostsApi {
    add(payload: AddHostPayload): Promise<HostRow>;
    probe(key: string): Promise<HostRow>;
}

export function createHostsApi(fetcher: typeof authFetch = authFetch): HostsApi {
    return {
        add: (payload) =>
            fetcher<HostRow>(HOSTS_ROUTE, {
                method: 'POST',
                body: JSON.stringify(payload),
            }),
        probe: (key) =>
            fetcher<HostRow>(`${HOSTS_ROUTE}/${encodeURIComponent(key)}/probe`, {
                method: 'POST',
            }),
    };
}

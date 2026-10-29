import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';

export const PEER_STATES = ['connecting', 'connected', 'disconnected', 'incompatible', 'unpaired', 'identity_changed'] as const;

export interface PeerRow {
    readonly key: string;
    readonly label: string;
    readonly peer_install_id: string;
    readonly fid: string;
    readonly initiator: boolean;
    readonly state: string;
    readonly protocol: number | null;
}

export interface DiscoveredMac {
    readonly name: string;
    readonly host: string;
    readonly port: number;
    readonly addresses: readonly string[];
    readonly fid: string;
    readonly state: string;
    readonly known_host: boolean;
}

export interface DiscoveredResponse {
    readonly discovered: readonly DiscoveredMac[];
    readonly advertise: boolean;
    readonly state: string;
    readonly browse_state: string;
}

export interface GrantRow {
    readonly grant_id: string;
    readonly peer_install_id: string;
    readonly fid: string;
    readonly label: string;
    readonly scopes: readonly string[];
    readonly created_at: string;
    readonly last_seen_at: string | null;
    readonly revoked_at: string | null;
}

export interface PairPayload {
    ssh_target: string;
    ssh_port?: number | null;
    remote_port?: number;
    typed_nonce?: string;
    typed_code?: string;
    discovered_name?: string;
}

export interface PairPending {
    readonly pending: true;
    readonly nonce: string;
    readonly sas: string;
    readonly label: string;
    readonly fid: string;
    readonly proof: string;
    readonly peer_owner_confirms: boolean;
    readonly expires_in: number;
}

export interface PendingPair {
    readonly nonce: string;
    readonly sas: string;
    readonly label: string;
    readonly fid: string;
    readonly proof: string;
    readonly initiator_accepted: boolean;
    readonly owner_confirmed: boolean;
    readonly expires_in: number;
}

export interface PairCode {
    readonly nonce: string;
    readonly code: string;
    readonly expires_in: number;
}

export interface RotateResult {
    readonly fid: string;
    readonly announced: number;
    readonly not_announced: number;
}

export interface FederationApi {
    discovered(): Promise<DiscoveredResponse>;
    setAdvertise(advertise: boolean): Promise<{ advertise: boolean; state: string }>;
    settings(): Promise<{ advertise: boolean; state: string }>;
    peers(): Promise<readonly PeerRow[]>;
    pair(payload: PairPayload): Promise<PairPending>;
    confirmPair(nonce: string, match: boolean): Promise<PeerRow | { cancelled: true }>;
    pending(): Promise<readonly PendingPair[]>;
    confirmPending(nonce: string): Promise<{ state: string }>;
    cancelPending(nonce: string): Promise<void>;
    unpair(key: string): Promise<void>;
    grants(): Promise<readonly GrantRow[]>;
    revoke(grantId: string): Promise<void>;
    beginCode(): Promise<PairCode>;
    rotate(): Promise<RotateResult>;
}

const ROUTE = '/federation';

export function errorCode(err: unknown): string | null {
    if (!(err instanceof ApiError)) return null;
    const payload = err.payload as { detail?: { code?: unknown } } | null;
    const code = payload?.detail?.code;
    return typeof code === 'string' ? code : err.code;
}

export async function readPackName(fetcher: typeof authFetch = authFetch): Promise<string | null> {
    const doc = await fetcher<{ pack_name?: string | null }>(`${ROUTE}/settings`);
    return typeof doc.pack_name === 'string' ? doc.pack_name : null;
}

export async function writePackName(name: string | null, fetcher: typeof authFetch = authFetch): Promise<string | null> {
    const doc = await fetcher<{ pack_name?: string | null }>(`${ROUTE}/settings`, { method: 'PATCH', body: JSON.stringify({ pack_name: name }) });
    return typeof doc.pack_name === 'string' ? doc.pack_name : null;
}

export function createFederationApi(fetcher: typeof authFetch = authFetch): FederationApi {
    const json = (method: string, body?: unknown): RequestInit =>
        body === undefined ? { method } : { method, body: JSON.stringify(body) };
    return {
        discovered: () => fetcher<DiscoveredResponse>(`${ROUTE}/discovered`),
        settings: () => fetcher(`${ROUTE}/settings`),
        setAdvertise: (advertise) => fetcher(`${ROUTE}/settings`, json('PATCH', { advertise })),
        peers: () => fetcher<readonly PeerRow[]>(`${ROUTE}/peers`),
        pair: (payload) => fetcher<PairPending>(`${ROUTE}/peers/pair`, json('POST', payload)),
        confirmPair: (nonce, match) => fetcher(`${ROUTE}/peers/pair/confirm`, json('POST', { nonce, match })),
        pending: () => fetcher<readonly PendingPair[]>(`${ROUTE}/pending-pairs`),
        confirmPending: (nonce) => fetcher(`${ROUTE}/pending-pairs/${encodeURIComponent(nonce)}/confirm`, json('POST')),
        cancelPending: async (nonce) => {
            await fetcher(`${ROUTE}/pending-pairs/${encodeURIComponent(nonce)}/cancel`, json('POST'));
        },
        unpair: async (key) => {
            await fetcher(`${ROUTE}/peers/${encodeURIComponent(key)}`, json('DELETE'));
        },
        grants: () => fetcher<readonly GrantRow[]>(`${ROUTE}/grants`),
        revoke: async (grantId) => {
            await fetcher(`${ROUTE}/grants/${encodeURIComponent(grantId)}`, json('DELETE'));
        },
        beginCode: () => fetcher<PairCode>(`${ROUTE}/pair/begin`, json('POST')),
        rotate: () => fetcher<RotateResult>(`${ROUTE}/key/rotate`, json('POST')),
    };
}

import { ApiError, authFetch } from '../sdk';

export interface ShareRow {
    id: string;
    session_id: string;
    label: string | null;
    created_at: string;
    expires_at: string;
    url?: string | null;
}

export interface ShareState {
    links: ShareRow[];
    relay_available: boolean;
}

export interface MintedShare {
    id: string;
    url: string;
    expires_at: string;
}

export const TTL_CHOICES: ReadonlyArray<{ seconds: number; key: string; count?: number }> = [
    { seconds: 900, key: 'cplug.share.ttl.minutes', count: 15 },
    { seconds: 3600, key: 'cplug.share.ttl.minutes', count: 60 },
    { seconds: 14400, key: 'cplug.share.ttl.hours', count: 4 },
    { seconds: 86400, key: 'cplug.share.ttl.day' },
];

export const DEFAULT_TTL_SECONDS = 3600;

export function mintShare(
    sessionId: string,
    ttlSeconds: number,
    label: string,
): Promise<MintedShare> {
    return authFetch<MintedShare>(
        `/sessions/${encodeURIComponent(sessionId)}/spectator-links`,
        {
            method: 'POST',
            body: JSON.stringify({
                ttl_seconds: ttlSeconds,
                label: label ? label : null,
            }),
        },
    );
}

export async function listShares(sessionId: string): Promise<ShareState> {
    const body = await authFetch<Partial<ShareState>>(
        `/sessions/${encodeURIComponent(sessionId)}/spectator-links`,
    );
    return { links: body.links ?? [], relay_available: body.relay_available === true };
}

export function isRelayUnavailable(error: unknown): boolean {
    if (!(error instanceof ApiError) || error.status !== 503) return false;
    const detail = (error.payload as { detail?: { code?: unknown } } | null)?.detail;
    return detail?.code === 'relay_unavailable';
}

export async function revokeShare(sessionId: string, linkId: string): Promise<void> {
    await authFetch<{ id: string }>(
        `/sessions/${encodeURIComponent(sessionId)}/spectator-links/${encodeURIComponent(linkId)}`,
        { method: 'DELETE' },
    );
}

export async function listAllShares(): Promise<ShareRow[]> {
    const body = await authFetch<{ links?: ShareRow[] }>('/spectator-links');
    return body.links ?? [];
}

export async function revokeAllShares(): Promise<string[]> {
    const body = await authFetch<{ ids?: string[] }>('/spectator-links', { method: 'DELETE' });
    return body.ids ?? [];
}

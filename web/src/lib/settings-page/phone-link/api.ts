import { authFetch } from '../../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export interface CertInfo {
    readonly issuer: string;
    readonly not_after: string;
    readonly environment: 'staging' | 'production';
}

export interface PairingView {
    readonly state: 'none' | 'open' | 'pending' | 'claimed' | 'failed';
    readonly locked?: boolean;
    readonly device: { readonly id: string; readonly label: string; readonly kind: string; readonly created_at: number } | null;
}

export interface LinkStatus {
    readonly enabled: boolean;
    readonly running: boolean;
    readonly tunnel: string;
    readonly hostname: string;
    readonly devices: number;
    readonly window_open: boolean;
    readonly pairing: PairingView;
    readonly error: string;
    readonly cert: CertInfo | null;
}

export interface DevicePush {
    readonly service: string;
    readonly last_result: { readonly status: number; readonly at: string } | null;
}

export interface Device {
    readonly id: string;
    readonly label: string;
    readonly kind: string;
    readonly created_at: number;
    readonly last_seen: number | null;
    readonly push: readonly DevicePush[];
}

export interface PairWindow {
    readonly url: string;
    readonly pair_url: string;
    readonly code: string;
    readonly expires_at: number;
    readonly qr: string;
    readonly qr_expires_at: number;
    readonly qr_rotate_seconds: number;
}

export interface RotatedQr {
    readonly url: string;
    readonly qr: string;
    readonly qr_expires_at: number;
}

const ROUTE = '/phone-link';

export const getStatus = (fetcher: Fetcher = authFetch) => fetcher<LinkStatus>(ROUTE);

export const setEnabled = (enabled: boolean, fetcher: Fetcher = authFetch) =>
    fetcher<LinkStatus>(ROUTE, { method: 'PUT', body: JSON.stringify({ enabled }) });

export const openWindow = (fetcher: Fetcher = authFetch) => fetcher<PairWindow>(`${ROUTE}/pairing-window`, { method: 'POST' });

export const acknowledgeFailures = (fetcher: Fetcher = authFetch) =>
    fetcher<unknown>(`${ROUTE}/pairing-window/acknowledge`, { method: 'POST' });

export const rotateQr = (fetcher: Fetcher = authFetch) => fetcher<RotatedQr>(`${ROUTE}/pairing-window/qr`, { method: 'POST' });

export const closeWindow = (fetcher: Fetcher = authFetch, keepalive = false) =>
    fetcher<unknown>(`${ROUTE}/pairing-window`, { method: 'DELETE', keepalive });

export async function listDevices(fetcher: Fetcher = authFetch): Promise<Device[]> {
    const rows = await fetcher<Device[]>(`${ROUTE}/devices`);
    return Array.isArray(rows) ? rows : [];
}

export const revokeDevice = (id: string, fetcher: Fetcher = authFetch) =>
    fetcher<unknown>(`${ROUTE}/devices/${encodeURIComponent(id)}`, { method: 'DELETE' });

export const utcMinute = (seconds: number): string => new Date(seconds * 1000).toISOString().slice(0, 16).replace('T', ' ');

export function countdown(seconds: number): string {
    const left = Math.max(0, Math.floor(seconds));
    return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
}

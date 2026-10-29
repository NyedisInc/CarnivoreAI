import { ApiError, authFetch } from '../../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export interface KindField {
    readonly name: string;
    readonly type: 'url' | 'secret' | 'text' | 'int' | 'enum' | 'list' | string;
    readonly required: boolean;
    readonly choices: readonly string[];
}

export interface Kind {
    readonly id: string;
    readonly label_key: string;
    readonly sms_like: boolean;
    readonly details_allowed: boolean;
    readonly virtual: boolean;
    readonly allow_private?: boolean;
    readonly public_fields: readonly KindField[];
    readonly secret_fields: readonly KindField[];
}

export interface Quiet {
    start: string;
    end: string;
}

export interface Extras {
    away: boolean;
    quiet: Quiet | null;
    reminder_minutes: number | null;
    projects: string[];
    details: boolean;
}

export interface Status {
    readonly last_ok_ts: number | null;
    readonly last_failure_ts: number | null;
    readonly last_failure: string | null;
    readonly consecutive_permanent_failures: number;
    readonly disabled_reason: string | null;
}

export interface Destination {
    readonly id: string;
    readonly kind: string;
    readonly name: string;
    readonly enabled: boolean;
    readonly scope: 'global' | 'local';
    readonly pinned: boolean;
    readonly config: Readonly<Record<string, unknown>>;
    readonly allow_private?: boolean;
    readonly allow_plain_http?: boolean;
    readonly secrets: Readonly<Record<string, { readonly set: boolean }>>;
    readonly extras: Extras;
    readonly status: Status | null;
}

export interface Settings {
    readonly paused: boolean;
    readonly destinations: readonly Destination[];
}

export interface DestinationBody {
    kind?: string;
    name?: string;
    enabled?: boolean;
    scope?: 'global' | 'local';
    config?: Record<string, unknown>;
    secrets?: Record<string, unknown>;
    allow_private?: boolean;
    allow_plain_http?: boolean;
}

export type ExtrasBody = Partial<Extras> & { scope?: 'global' | 'local' };

export interface TestAnswer {
    readonly ok: boolean;
    readonly failure: string | null;
    readonly status_code: number | null;
}

const BASE = '/notifications';
const json = (body: unknown): string => JSON.stringify(body);
const seg = (id: string): string => encodeURIComponent(id);

export const isRateLimited = (error: unknown): boolean => error instanceof ApiError && error.status === 429;

export async function fetchKinds(fetcher: Fetcher = authFetch): Promise<Kind[]> {
    const body = await fetcher<{ kinds?: Kind[] } | null>(`${BASE}/types`);
    return Array.isArray(body?.kinds) ? body.kinds : [];
}

export async function fetchSettings(fetcher: Fetcher = authFetch): Promise<Settings> {
    const body = await fetcher<Partial<Settings> | null>(`${BASE}/settings`);
    return { paused: body?.paused === true, destinations: Array.isArray(body?.destinations) ? body.destinations : [] };
}

export const createDestination = (body: DestinationBody, fetcher: Fetcher = authFetch) =>
    fetcher<{ destination: Destination; signing_secret?: string }>(`${BASE}/destinations`, { method: 'POST', body: json(body) });

export const patchDestination = (id: string, body: DestinationBody, fetcher: Fetcher = authFetch) =>
    fetcher<{ destination: Destination }>(`${BASE}/destinations/${seg(id)}`, { method: 'PATCH', body: json(body) });

export const deleteDestination = (id: string, fetcher: Fetcher = authFetch) =>
    fetcher<{ deleted: boolean }>(`${BASE}/destinations/${seg(id)}`, { method: 'DELETE' });

export const putExtras = (id: string, body: ExtrasBody, fetcher: Fetcher = authFetch) =>
    fetcher<{ destination: Destination }>(`${BASE}/destinations/${seg(id)}/extras`, { method: 'PUT', body: json(body) });

export const testDestination = (id: string, fetcher: Fetcher = authFetch) =>
    fetcher<TestAnswer>(`${BASE}/destinations/${seg(id)}/test`, { method: 'POST' });

export const resetOverride = (path: string, fetcher: Fetcher = authFetch) =>
    fetcher<{ revision: number; reset: boolean }>(`${BASE}/overrides?path=${encodeURIComponent(path)}`, { method: 'DELETE' });

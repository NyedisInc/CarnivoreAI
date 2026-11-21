import { authFetch } from '../../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export interface TypeRow {
    readonly id: string;
    readonly family: string;
    readonly label_key: string;
    readonly description_key: string;
    readonly hidden?: boolean;
    readonly defaults: {
        readonly outside_locked_off: boolean;
        readonly screen_surface: string;
    };
}

export interface Family {
    readonly id: string;
    readonly label_key: string;
}

export interface Link {
    readonly kind: string;
    readonly base: string;
    readonly reason: string;
}

export interface RoutingSettings {
    readonly paused: boolean;
    readonly link: Link;
}

export const EMPTY_SETTINGS: RoutingSettings = { paused: false, link: { kind: 'none', base: '', reason: '' } };

const BASE = '/notifications';
const json = (body: unknown): string => JSON.stringify(body);

export async function fetchRegistry(fetcher: Fetcher = authFetch): Promise<{ families: Family[]; types: TypeRow[]; aliases: Record<string, string> }> {
    const body = await fetcher<{ families?: Family[]; types?: TypeRow[]; aliases?: Record<string, string> } | null>(`${BASE}/types`);
    const aliases = body?.aliases && typeof body.aliases === 'object' ? body.aliases : {};
    return { families: Array.isArray(body?.families) ? body.families : [], types: Array.isArray(body?.types) ? body.types : [], aliases };
}

export async function fetchRouting(fetcher: Fetcher = authFetch): Promise<RoutingSettings> {
    const b = await fetcher<Partial<RoutingSettings> | null>(`${BASE}/settings`);
    return { paused: b?.paused === true, link: b?.link ?? EMPTY_SETTINGS.link };
}

export const putPaused = (paused: boolean, fetcher: Fetcher = authFetch) =>
    fetcher<unknown>(`${BASE}/settings`, { method: 'PUT', body: json({ paused }) });

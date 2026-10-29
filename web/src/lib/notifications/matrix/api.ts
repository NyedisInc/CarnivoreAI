import { authFetch } from '../../../opscenter/api/auth.svelte';
import { resetOverride } from '../destinations/api';

export type Fetcher = typeof authFetch;

export const SCREEN = 'screen';

export interface TypeRow {
    readonly id: string;
    readonly family: string;
    readonly label_key: string;
    readonly description_key: string;
    readonly defaults: {
        readonly outside_locked_off: boolean;
        readonly screen_surface: string;
    };
}

export interface Family {
    readonly id: string;
    readonly label_key: string;
}

export interface Cell {
    readonly value: boolean;
    readonly source: 'global' | 'local' | 'locked' | 'default';
    readonly locked: boolean;
}

export interface Link {
    readonly kind: string;
    readonly base: string;
    readonly reason: string;
}

export interface Column {
    readonly id: string;
    readonly name: string;
    readonly kind: string;
    readonly enabled: boolean;
    readonly scope: string;
}

export interface RoutingSettings {
    readonly paused: boolean;
    readonly link: Link;
    readonly defaults: Readonly<Record<string, boolean>>;
    readonly screen: Readonly<Record<string, Cell>>;
    readonly ticks: Readonly<Record<string, Readonly<Record<string, Cell>>>>;
    readonly destinations: readonly Column[];
}

export const EMPTY_SETTINGS: RoutingSettings = {
    paused: false, link: { kind: 'none', base: '', reason: '' }, defaults: {}, screen: {}, ticks: {}, destinations: [],
};

const BASE = '/notifications';
const json = (body: unknown): string => JSON.stringify(body);

export async function fetchRegistry(fetcher: Fetcher = authFetch): Promise<{ families: Family[]; types: TypeRow[] }> {
    const body = await fetcher<{ families?: Family[]; types?: TypeRow[] } | null>(`${BASE}/types`);
    return { families: Array.isArray(body?.families) ? body.families : [], types: Array.isArray(body?.types) ? body.types : [] };
}

export async function fetchRouting(fetcher: Fetcher = authFetch): Promise<RoutingSettings> {
    const b = await fetcher<Partial<RoutingSettings> | null>(`${BASE}/settings`);
    return {
        paused: b?.paused === true,
        link: b?.link ?? EMPTY_SETTINGS.link,
        defaults: b?.defaults ?? {},
        screen: b?.screen ?? {},
        ticks: b?.ticks ?? {},
        destinations: Array.isArray(b?.destinations) ? b.destinations : [],
    };
}

export const putTick = (body: { column: string; type_id: string; value: boolean; scope?: 'global' | 'local' }, fetcher: Fetcher = authFetch) =>
    fetcher<{ revision: number; cell: Cell }>(`${BASE}/ticks`, { method: 'PUT', body: json(body) });

export const putDefault = (type_id: string, value: boolean, fetcher: Fetcher = authFetch) =>
    fetcher<{ revision: number; defaults: Record<string, boolean> }>(`${BASE}/defaults`, { method: 'PUT', body: json({ type_id, value }) });

export const putPaused = (paused: boolean, fetcher: Fetcher = authFetch) =>
    fetcher<unknown>(`${BASE}/settings`, { method: 'PUT', body: json({ paused }) });

export const resetTick = (column: string, typeId: string, fetcher: Fetcher = authFetch) =>
    resetOverride(`tick/${column}/${typeId}`, fetcher);

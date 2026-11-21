import { authFetch } from '../../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export interface Style {
    readonly sound: string;
    readonly urgency: string;
    readonly source: 'global' | 'default';
    readonly corner: boolean;
}

export interface StylesDoc {
    readonly styles: Readonly<Record<string, Style>>;
    readonly sounds: readonly string[];
    readonly urgencies: readonly string[];
}

export type StylePatch = { sound?: string; urgency?: string; corner?: boolean };

const BASE = '/notifications';
const seg = (id: string): string => encodeURIComponent(id);

export async function fetchStyles(fetcher: Fetcher = authFetch): Promise<StylesDoc> {
    const b = await fetcher<Partial<StylesDoc> | null>(`${BASE}/styles`);
    return {
        styles: b?.styles ?? {},
        sounds: Array.isArray(b?.sounds) ? b.sounds : [],
        urgencies: Array.isArray(b?.urgencies) ? b.urgencies : [],
    };
}

export const putStyle = (typeId: string, patch: StylePatch, fetcher: Fetcher = authFetch) =>
    fetcher<Partial<StylesDoc> | null>(`${BASE}/styles/${seg(typeId)}`, { method: 'PUT', body: JSON.stringify(patch) });

export type Target = 'app' | 'desk' | 'phone' | 'corner';

export interface RouteCell {
    readonly value: boolean | null;
    readonly source: 'global' | 'default' | 'unknown' | 'locked';
    readonly locked: boolean;
}

export interface RouteComputer {
    readonly install_id: string;
    readonly label: string;
    readonly self: boolean;
    readonly online: boolean | null;
    readonly syncs: boolean;
    readonly hue: number;
}

export interface RouteType {
    readonly on: boolean;
    readonly locked: { readonly phone: boolean; readonly corner: boolean };
    readonly cells: Readonly<Record<string, Readonly<Record<Target, RouteCell>>>>;
}

export interface RoutesBody {
    readonly revision: number;
    readonly self: string;
    readonly phone_paired: boolean;
    readonly computers: readonly RouteComputer[];
    readonly types: Readonly<Record<string, RouteType>>;
    readonly skipped?: readonly string[];
}

export type TestTarget = 'phone' | 'desktop' | 'app';

export interface SendTestAnswer {
    readonly ok: boolean;
    readonly failure: string | null;
    readonly status_code: number | null;
    readonly target: string;
    readonly delivered: number;
}

export async function fetchRoutes(fetcher: Fetcher = authFetch): Promise<RoutesBody> {
    const b = await fetcher<Partial<RoutesBody> | null>(`${BASE}/routes`);
    return { revision: b?.revision ?? 0, self: b?.self ?? '', phone_paired: b?.phone_paired === true, computers: b?.computers ?? [], types: b?.types ?? {} };
}

export const putRoutes = (body: { type_ids: readonly string[]; computer: string; target: Target; value: boolean }, fetcher: Fetcher = authFetch) =>
    fetcher<RoutesBody>(`${BASE}/routes`, { method: 'PUT', body: JSON.stringify(body) });

export const putMaster = (typeIds: readonly string[], value: boolean, fetcher: Fetcher = authFetch) =>
    fetcher<RoutesBody>(`${BASE}/master`, { method: 'PUT', body: JSON.stringify({ type_ids: typeIds, value }) });

export const sendTest = (typeId: string, target: TestTarget, fetcher: Fetcher = authFetch) =>
    fetcher<SendTestAnswer>(`${BASE}/test`, { method: 'POST', body: JSON.stringify({ type_id: typeId, target }) });

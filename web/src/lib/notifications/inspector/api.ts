import { authFetch } from '../../../opscenter/api/auth.svelte';
import type { TestAnswer } from '../destinations/api';

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

export const sendTypedTest = (destId: string, typeId: string, fetcher: Fetcher = authFetch) =>
    fetcher<TestAnswer>(`${BASE}/destinations/${seg(destId)}/test`, { method: 'POST', body: JSON.stringify({ type_id: typeId }) });

export async function fetchComputerName(fetcher: Fetcher = authFetch): Promise<string> {
    const b = await fetcher<{ self?: { label?: string } } | null>('/computers');
    return b?.self?.label ?? '';
}

import { ApiError, authFetch } from '../sdk';

const ROUTE = '/cplugs/save/folders';
const PLUGIN_ROUTE = '/cplugs/save';
export const FOLDER_OPT_OUT_SETTING = 'vaultFolderOptOut';

export type Fetcher = typeof authFetch;

export interface FolderUnit {
    readonly unit: string;
    readonly plugin: string;
    readonly data_id: string;
    readonly plugin_name_key: string;
    readonly root: string;
    readonly marked: boolean;
    readonly backup_on: boolean;
    readonly points: number;
    readonly bytes: number;
    readonly last_point_at: string | null;
}

export interface FolderPoint {
    readonly point_id: string;
    readonly created_at: string;
    readonly files: number;
    readonly bytes: number;
}

export interface FolderRestored {
    readonly unit: string;
    readonly point_id: string;
    readonly target: string;
    readonly written: number;
    readonly bytes: number;
}

export async function fetchFolders(fetcher: Fetcher = authFetch): Promise<readonly FolderUnit[]> {
    const body = await fetcher<{ folders?: readonly FolderUnit[] }>(ROUTE);
    return Array.isArray(body?.folders) ? body.folders : [];
}

export async function fetchFolderPoints(unit: string, fetcher: Fetcher = authFetch): Promise<readonly FolderPoint[]> {
    const body = await fetcher<{ points?: readonly FolderPoint[] }>(`${ROUTE}/${encodeURIComponent(unit)}/points`);
    return Array.isArray(body?.points) ? body.points : [];
}

export async function restoreFolder(unit: string, pointId: string, fetcher: Fetcher = authFetch): Promise<FolderRestored> {
    return fetcher<FolderRestored>(`${ROUTE}/${encodeURIComponent(unit)}/restore`, { method: 'POST', body: JSON.stringify({ point_id: pointId }) });
}

export function optOutUnits(text: unknown): string[] {
    return typeof text === 'string' ? text.replace(/,/g, ' ').split(/\s+/).filter((part) => part.length > 0) : [];
}

export async function saveFolderSwitch(unit: string, on: boolean, fetcher: Fetcher = authFetch): Promise<void> {
    for (let attempt = 0; ; attempt += 1) {
        const current = await fetcher<{ revision?: number; settings?: Record<string, unknown> }>(PLUGIN_ROUTE);
        const off = new Set(optOutUnits(current.settings?.[FOLDER_OPT_OUT_SETTING]));
        if (on) off.delete(unit);
        else off.add(unit);
        try {
            await fetcher(PLUGIN_ROUTE, {
                method: 'PUT',
                body: JSON.stringify({ revision: current.revision ?? 0, settings: { [FOLDER_OPT_OUT_SETTING]: [...off].sort().join(',') } }),
            });
            return;
        } catch (error) {
            if (attempt >= 1 || !(error instanceof ApiError) || error.status !== 409) throw error;
        }
    }
}

const AGO_UNITS: readonly (readonly [seconds: number, key: string])[] = [
    [86_400, 'cplug.save.folders.ago_days'],
    [3_600, 'cplug.save.folders.ago_hours'],
    [60, 'cplug.save.folders.ago_minutes'],
];

export function agoText(iso: string | null | undefined, nowMs: number, t: (key: string, params?: Record<string, unknown>) => string): string {
    const at = iso ? Date.parse(iso) : Number.NaN;
    if (!Number.isFinite(at)) return t('cplug.save.folders.never');
    const seconds = Math.max(0, Math.floor((nowMs - at) / 1000));
    const unit = AGO_UNITS.find(([size]) => seconds >= size);
    return unit ? t(unit[1], { count: Math.floor(seconds / unit[0]) }) : t('cplug.save.folders.just_now');
}

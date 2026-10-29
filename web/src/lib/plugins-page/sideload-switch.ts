import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';
import type { Translate } from '../sessions/types';

export interface SideloadGit {
    url: string;
    ref: string | null;
    subdir: string;
    commit: string;
    synced_at: number | null;
}

export interface SideloadItem {
    id: string;
    item_id: string;
    source: string;
    synced_at: number | null;
    changed: string[];
    git?: SideloadGit | null;
}

export interface SideloadStatus {
    enabled: boolean;
    expires_at: number | null;
    hours?: number | null;
    items: SideloadItem[];
}

export interface GitRequest {
    url: string;
    ref?: string | null;
    subdir?: string | null;
    name?: string | null;
}

export const DURATION_HOURS = [1, 12, 24, 168] as const;
export const DEFAULT_HOURS = 12;
export const UNTIL_OFF = 'off';

export const KNOWN_REFUSALS = [
    'sideload_off', 'source_missing', 'source_unsafe', 'source_too_big', 'manifest_invalid', 'name_taken', 'name_reserved',
    'name_invalid', 'git_url_refused', 'ref_invalid', 'subdir_invalid', 'git_failed', 'git_unavailable', 'git_timeout',
] as const;

export function loadSideload(fetcher: typeof authFetch = authFetch): Promise<SideloadStatus> {
    return fetcher<SideloadStatus>('/cplug-owner/sideload');
}

export function saveSideload(enabled: boolean, hours?: number | null, fetcher: typeof authFetch = authFetch): Promise<SideloadStatus> {
    const body = enabled && hours !== undefined ? { enabled, hours } : { enabled };
    return fetcher<SideloadStatus>('/cplug-owner/sideload/switch', { method: 'PUT', body: JSON.stringify(body) });
}

export function sideloadFolder(path: string, name?: string | null, fetcher: typeof authFetch = authFetch): Promise<unknown> {
    return fetcher('/cplug-owner/sideload', { method: 'POST', body: JSON.stringify(name ? { path, name } : { path }) });
}

export function sideloadGit(request: GitRequest, fetcher: typeof authFetch = authFetch): Promise<unknown> {
    const body: Record<string, string> = { url: request.url };
    for (const key of ['ref', 'subdir', 'name'] as const) {
        const value = request[key]?.trim();
        if (value) body[key] = value;
    }
    return fetcher('/cplug-owner/sideload/git', { method: 'POST', body: JSON.stringify(body) });
}

export function removeSideload(name: string, fetcher: typeof authFetch = authFetch): Promise<unknown> {
    return fetcher(`/cplug-owner/sideload?name=${encodeURIComponent(name)}`, { method: 'DELETE' });
}

export function resyncSideload(item: SideloadItem, fetcher: typeof authFetch = authFetch): Promise<unknown> {
    if (item.git) {
        return sideloadGit({ url: item.git.url, ref: item.git.ref, subdir: item.git.subdir, name: item.id }, fetcher);
    }
    return sideloadFolder(item.source, item.id, fetcher);
}

export function durationValue(hours: number | null | undefined): string {
    return hours === null ? UNTIL_OFF : String(hours ?? DEFAULT_HOURS);
}

export function hoursOf(value: string): number | null {
    return value === UNTIL_OFF ? null : Number(value);
}

export function sourceLine(item: SideloadItem, t: Translate): string {
    if (!item.git) return item.source;
    const repo = item.git.url.replace(/^[a-z]+:\/\//, '').replace(/^[^@/]+@/, '').replace(/\.git$/, '');
    const ref = item.git.ref || t('plugins.page.sideload.default_branch');
    const sub = item.git.subdir ? `/${item.git.subdir}` : '';
    return `${repo}${sub} @ ${ref} (${item.git.commit.slice(0, 7)})`;
}

export function refusalCode(error: unknown): string | null {
    if (!(error instanceof ApiError)) return null;
    if (error.code) return error.code;
    const detail = (error.payload as { detail?: { code?: unknown } } | null)?.detail;
    return typeof detail?.code === 'string' ? detail.code : null;
}

export function refusalText(error: unknown, t: Translate): string {
    const code = refusalCode(error);
    const said = error instanceof Error ? error.message : '';
    if (code && (KNOWN_REFUSALS as readonly string[]).includes(code)) {
        const words = t(`plugins.page.sideload.refused.${code}`);
        return code === 'git_failed' || code === 'manifest_invalid' ? `${words}: ${said}` : words;
    }
    return said || t('plugins.page.sideload.failed');
}

export function untilWhen(status: SideloadStatus | null, t: Translate): string | null {
    if (!status?.enabled) return null;
    if (status.expires_at === null) return t('plugins.page.sideload.until_off');
    const when = new Date(status.expires_at * 1000).toLocaleString(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit' });
    return t('plugins.page.sideload.until', { when });
}

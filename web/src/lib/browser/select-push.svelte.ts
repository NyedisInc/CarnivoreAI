import { authFetch } from '../../opscenter/api/auth.svelte';
import { resourcePush } from '../resource-push/boot';
import { LIVENESS, familyOf } from '../resource-push/store';
import { BROWSER_ID, browsers, type BrowserInfo } from './api.svelte';
import { openBrowser } from './screen-host';
import { activate as activateBrowserRow } from '../drawer/browser-rows';
import type { PageInfo } from './page-frame';
import { openPages } from './pages.svelte';

export const BROWSER_SELECT_TOPIC = 'browser_select';

export const FRESH_S = 60;

export const BROWSER_ROW_PREFIX = 'browser:';

export interface ServerSelect {
    seq: number;
    kind?: 'browser' | 'page';
    browser_id?: string;
    page_id?: string;
    title?: string;
    age_s?: number;
}

export type PageTarget =
    | { url: string; title?: string }
    | { huddle_artifact: { item: number; artifact: string }; title?: string };

export interface OpenAnswer {
    page?: PageInfo;
    browser?: BrowserInfo;
    select: ServerSelect;
}

interface DrawerGlobals {
    SessionSidebar?: unknown;
}

let appliedSeq = 0;
let following = false;

export function selectBrowserItem(id: string): boolean {
    if (!BROWSER_ID.test(id)) return false;
    const g = globalThis as unknown as DrawerGlobals;
    if (activateBrowserRow(g.SessionSidebar as { _closeAfterSwitch?: () => void } | null ?? null, `${BROWSER_ROW_PREFIX}${id}`)) return true;
    return openBrowser(id);
}

export async function applyServerSelect(pointer: ServerSelect | null): Promise<boolean> {
    if (!pointer || typeof pointer.seq !== 'number' || pointer.seq === appliedSeq) return false;
    appliedSeq = pointer.seq;
    if (typeof pointer.age_s !== 'number' || pointer.age_s > FRESH_S) return false;
    const id = pointer.kind === 'page' ? pointer.page_id : pointer.browser_id;
    if (typeof id !== 'string' || !BROWSER_ID.test(id)) return false;
    try {
        await (pointer.kind === 'page' ? openPages : browsers).refresh(true);
    } catch (err) {
        console.warn('browser select: list refresh failed', err);
    }
    return selectBrowserItem(id);
}

export async function refreshBrowserSelect(): Promise<void> {
    try {
        const body = await authFetch<{ select: ServerSelect | null }>('/browsers/selected');
        await applyServerSelect(body?.select ?? null);
    } catch (err) {
        console.debug('browser select: read failed', err);
    }
}

export function followBrowserSelect(): void {
    if (following) return;
    following = true;
    const push = resourcePush();
    push.onChange((topics) => {
        const named = topics.some((topic) => familyOf(topic) === BROWSER_SELECT_TOPIC);
        const hello = topics.includes(LIVENESS) && push.isLive(BROWSER_SELECT_TOPIC);
        if (named || hello) void refreshBrowserSelect();
    });
    void refreshBrowserSelect();
}

export async function openPage(target: PageTarget): Promise<OpenAnswer> {
    const answer = await authFetch<OpenAnswer>('/browsers/open', { method: 'POST', body: JSON.stringify(target) });
    if (following) await applyServerSelect(answer.select);
    return answer;
}

export function resetBrowserSelectForTest(): void {
    appliedSeq = 0;
    following = false;
}

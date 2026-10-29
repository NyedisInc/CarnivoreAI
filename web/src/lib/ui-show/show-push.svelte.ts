import { authFetch } from '../../opscenter/api/auth.svelte';
import { thisTabId } from '../../opscenter/api/size-master.svelte';
import { desktopBridge, hasDesktopCapability } from '../settings-page/desktop-bridge';
import { resourcePush } from '../resource-push/boot';
import { LIVENESS, familyOf } from '../resource-push/store';
import { browserSelectors, type ShowKind, type ShowSelectors } from './selectors';

export const UI_SHOW_TOPIC = 'ui_show';

export const FRESH_S = 60;

export interface ShowPointer {
    seq: number;
    kind: ShowKind;
    id: string;
    tmux_session?: string | null;
    title?: string;
    target_client_id?: string;
    age_s?: number;
}

let appliedSeq = 0;
let following = false;

async function raiseThisWindow(): Promise<void> {
    try {
        const bridge = desktopBridge();
        if (bridge && hasDesktopCapability('raiseWindow', bridge)) await bridge.raiseWindow?.();
    } catch (err) {
        console.debug('ui show: raise failed', err);
    }
}

export async function applyShow(
    pointer: ShowPointer | null,
    selectors: ShowSelectors = browserSelectors(),
    clientId: string | null = thisTabId(),
): Promise<boolean> {
    if (!pointer || typeof pointer.seq !== 'number' || pointer.seq === appliedSeq) return false;
    if (!clientId || pointer.target_client_id !== clientId) return false;
    appliedSeq = pointer.seq;
    if (typeof pointer.age_s !== 'number' || pointer.age_s > FRESH_S) return false;
    const shown = await showPointer(pointer, selectors);
    if (shown) await raiseThisWindow();
    return shown;
}

async function showPointer(pointer: ShowPointer, selectors: ShowSelectors): Promise<boolean> {
    try {
        switch (pointer.kind) {
            case 'session': return await selectors.session(pointer.id, pointer.tmux_session ?? '');
            case 'file': return await selectors.file(pointer.id);
            case 'browser': return await selectors.browser(pointer.id);
            case 'board': return await selectors.board(pointer.id);
            case 'layout': return await selectors.layout(pointer.id);
            case 'task_manager': return await selectors.taskManager();
            default: return false;
        }
    } catch (err) {
        console.warn('ui show: the item could not be shown', pointer.kind, err);
        return false;
    }
}

export async function refreshUiShow(): Promise<void> {
    try {
        const body = await authFetch<{ show: ShowPointer | null }>('/ui/show');
        await applyShow(body?.show ?? null);
    } catch (err) {
        console.debug('ui show: read failed', err);
    }
}

export function followUiShow(): void {
    if (following) return;
    following = true;
    const push = resourcePush();
    push.onChange((topics) => {
        const named = topics.some((topic) => familyOf(topic) === UI_SHOW_TOPIC);
        const hello = topics.includes(LIVENESS) && push.isLive(UI_SHOW_TOPIC);
        if (named || hello) void refreshUiShow();
    });
    void refreshUiShow();
}

export function resetUiShowForTest(): void {
    appliedSeq = 0;
    following = false;
}

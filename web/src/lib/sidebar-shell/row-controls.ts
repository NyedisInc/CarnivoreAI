import { closestTo, refetch, rg, type RowController } from './row-globals';
import { openSessionAutomations } from '../automations/schedule-prefill';

function titleFor(el: Element, attr: string): string | null {
    const nameEl = closestTo(el, '.session-sidebar-row')?.querySelector('.session-sidebar-row-name');
    return nameEl ? nameEl.textContent : el.getAttribute(attr);
}

export async function toggleKeepAwake(ctrl: RowController, el: Element): Promise<void> {
    const store = rg().CloudeWeb?.autoSleep;
    const name = el.getAttribute('data-keep-awake-session');
    if (!store || !name) return;
    const on = store.isKeptAwake(name);
    if (on === null) return;
    await store.setKeepAwake(name, !on);
    ctrl.repaint?.();
}

export async function openShare(ctrl: RowController, el: Element): Promise<void> {
    const run = rg().CloudeWeb?.rowMenu?.runCplug;
    if (typeof run !== 'function') {
        console.error('SessionSidebar: the row menu bridge (CloudeWeb.rowMenu) is not published, the share dialog cannot open');
        return;
    }
    await run('share', {
        name: el.getAttribute('data-share-session') || '',
        sessionId: el.getAttribute('data-share-session-id') || null,
    });
    await refetch(ctrl);
}

export function openSubagents(el: Element): void {
    const open = rg().CloudeWeb?.openSubagentList;
    if (typeof open !== 'function') {
        console.error('SessionSidebarSubagents: the compiled list is not loaded');
        return;
    }
    open(el, el.getAttribute('data-subagents-session-id'), titleFor(el, 'data-subagents-session'));
}

export function openTimers(el: Element): void {
    const open = rg().CloudeWeb?.openTimerList;
    if (typeof open !== 'function') {
        console.error('SessionSidebarTimers: the compiled list is not loaded');
        return;
    }
    open(el, el.getAttribute('data-timers-session-id'), titleFor(el, 'data-timers-session'));
}

export function openSessionAutomationsFor(el: Element): void {
    const uuid = el.getAttribute('data-automations-session-uuid');
    if (!uuid) return;
    if (!openSessionAutomations(uuid)) {
        console.error('SessionSidebar: the Automations page is not loaded');
    }
}

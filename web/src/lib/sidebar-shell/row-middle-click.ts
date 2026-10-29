import { t } from '../i18n/index.svelte';
import { confirmOk, onMiddleClick } from '../confirm-ok/confirm-ok';
import { KIND_BROWSER, KIND_LAYOUT, kindOf } from '../drawer/bucketing';
import { sleepRows } from './heading-project-actions';
import { announceFailure, reasonOf, refetchDrawer } from './interaction-globals';
import type { SidebarRow } from './legacy';
import { closeLiveRow } from './row-activate';
import { closestTo, dataOf, drawer, rg } from './row-globals';
import { contextFromTrigger } from '../item-menu/row-context';

type DrawerRow = SidebarRow & { asleep?: boolean; label?: string; kind?: string; session_uuid?: string | null };

interface CloseGlobals {
    API?: { killAsleepSession?(uuid: string): Promise<unknown> };
    SessionRowMenuActions?: { run?(item: string, ctx: unknown): Promise<unknown> | undefined };
}

export type MiddleAction = 'sleep' | 'close-sleeping' | 'close-live' | 'close-menu' | 'none';

function drawerRowOf(rowEl: Element): DrawerRow | null {
    const name = dataOf(rowEl, 'name');
    const uuid = dataOf(rowEl, 'sessionUuid');
    const rows = (drawer() as { _rows?: DrawerRow[] } | null)?._rows;
    if (!Array.isArray(rows)) return null;
    if (uuid) return rows.find((r) => r.session_uuid === uuid) ?? null;
    return name ? rows.find((r) => r.name === name) ?? null : null;
}

export function middleActionFor(rowEl: Element, row: DrawerRow | null): MiddleAction {
    const kind = row ? kindOf(row) : dataOf(rowEl, 'kind');
    if (kind === KIND_BROWSER || kind === KIND_LAYOUT) return 'close-menu';
    if (!row) return 'none';
    if (row.closed === true) return 'none';
    if (row.asleep || dataOf(rowEl, 'asleep') === '1') return row.session_uuid ? 'close-sleeping' : 'none';
    if (kind === 'terminal') return 'close-live';
    return row.session_uuid ? 'sleep' : 'none';
}

function ask(verb: 'sleep' | 'close' | 'close_sleeping', label: string): Promise<boolean> {
    return confirmOk({
        title: t(`sidebar.row.${verb}_confirm.title`),
        message: t(`sidebar.row.${verb}_confirm.message`, { name: label }),
    });
}

async function closeThroughMenu(rowEl: Element): Promise<void> {
    const g = rg() as unknown as CloseGlobals;
    const ctx = contextFromTrigger(rowEl.querySelector('[data-row-menu]'))
        || { name: dataOf(rowEl, 'name'), kind: dataOf(rowEl, 'kind') || 'layout', label: '' };
    const run = g.SessionRowMenuActions?.run;
    if (typeof run !== 'function') throw new Error(t('sidebar.row.close_unavailable'));
    await run.call(g.SessionRowMenuActions, 'close', ctx);
}

export async function middleClickRow(rowEl: Element): Promise<boolean> {
    const row = drawerRowOf(rowEl);
    const action = middleActionFor(rowEl, row);
    if (action === 'none') return false;
    const label = row?.label || row?.name || dataOf(rowEl, 'name');
    const ctrl = drawer();
    try {
        if (action === 'sleep') {
            if (!(await ask('sleep', label))) return false;
            return (await sleepRows([row as DrawerRow], label)).slept > 0;
        }
        if (action === 'close-sleeping') {
            if (!(await ask('close_sleeping', label))) return false;
            const globals = rg() as unknown as CloseGlobals;
            const kill = globals.API?.killAsleepSession;
            if (typeof kill !== 'function') throw new Error(t('sidebar.row.close_unavailable'));
            await kill.call(globals.API, (row as DrawerRow).session_uuid as string);
            await refetchDrawer();
            return true;
        }
        if (!(await ask('close', label))) return false;
        if (action === 'close-live' && ctrl) await closeLiveRow(ctrl, dataOf(rowEl, 'name'), rowEl, 'close');
        else await closeThroughMenu(rowEl);
        return true;
    } catch (err) {
        announceFailure(t('sidebar.row.close_failed', { name: label, reason: reasonOf(err) }));
        return false;
    }
}

export const MIDDLE_CLICK_ACTION: (rowEl: Element) => Promise<boolean> = middleClickRow;

export function onRowAuxClick(e: MouseEvent): void {
    const row = closestTo(e.target, '.session-sidebar-row');
    if (!row) return;
    onMiddleClick(e, () => void MIDDLE_CLICK_ACTION(row));
}

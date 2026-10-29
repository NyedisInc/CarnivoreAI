import { t } from '../i18n/index.svelte';
import { runWake } from '../drawer/row-menu-sleep';
import { activate as activateBrowserRow } from '../drawer/browser-rows';
import { runRestart as runRestartFlow } from '../drawer/restart-click';
import { closeMenuPagesExcept } from '../menu-page/menu-page-shell.svelte';
import { announce } from './interaction-globals';
import {
    closestTo, dataOf, rg, type NavToken, type RowController,
} from './row-globals';
import { ARM_GRACE_MS, armWake, disarmWake, isArmableRow, refocusRow, wakeArm } from './wake-arm.svelte';

const waking = new Set<string>();

export function paintSelection(ctrl: RowController): void {
    const g = rg();
    const pending = ctrl._pendingSelection;
    const current = !!pending && (!g.NavigationGeneration || g.NavigationGeneration.isCurrent(pending.nav));
    let name: string | null | undefined;
    if (current && pending) {
        name = pending.name;
    } else {
        const LP = g.CloudeWeb?.layoutPage;
        const open = (LP && typeof LP.isActive === 'function' && LP.isActive()
            && typeof LP.current === 'function') ? LP.current() : null;
        const browser = g.CloudeWeb?.browsers?.showing?.() ?? null;
        name = open ? `layout:${open.uuid}` : browser ? `browser:${browser}` : ctrl._activeTmuxName;
    }
    for (const row of Array.from(ctrl.listEl?.querySelectorAll<HTMLElement>('.session-sidebar-row') || [])) {
        const want = row.dataset.name === name ? 'true' : 'false';
        if (row.getAttribute('aria-selected') !== want) row.setAttribute('aria-selected', want);
    }
}

export function wokenRowElement(ctrl: RowController, sessionUuid: string): HTMLElement | null {
    let live: string | null = null;
    for (const r of ctrl._rows || []) {
        if (r && !r.asleep && r.session_uuid === sessionUuid) { live = r.name; break; }
    }
    if (!live) return null;
    for (const el of Array.from(document.querySelectorAll<HTMLElement>('.session-sidebar-row'))) {
        if (el.dataset.name === live && el.dataset.asleep !== '1') return el;
    }
    return null;
}

async function performWake(ctrl: RowController, rowEl: Element): Promise<void> {
    const g = rg();
    const name = dataOf(rowEl, 'name');
    let row = null;
    for (const r of ctrl._rows || []) {
        if (r && r.name === name) { row = r; break; }
    }
    if (!row) return;
    const sessionUuid = String(row.session_uuid || '');
    if (sessionUuid && waking.has(sessionUuid)) return;
    if (sessionUuid) waking.add(sessionUuid);
    try {
        await runWake({
            name, label: (row.label != null && String(row.label)) || '', sessionUuid, surface: 'sidebar',
        });
    } finally {
        if (sessionUuid) waking.delete(sessionUuid);
    }
}

function inVisibleDrawer(rowEl: Element): boolean {
    if (!rowEl.isConnected || !closestTo(rowEl, '#session-sidebar-list')) return false;
    const panel = closestTo(rowEl, '.session-sidebar-panel');
    return !!panel && (panel.classList.contains('session-sidebar-panel--open')
        || document.body.classList.contains('session-sidebar-pinned'));
}

export function armAsleepRow(rowEl: Element): boolean {
    if (dataOf(rowEl, 'asleep') !== '1') return false;
    if (!isArmableRow(rowEl) || !inVisibleDrawer(rowEl)) return false;
    const name = dataOf(rowEl, 'name');
    if (!name) return false;
    if (!armWake(name, dataOf(rowEl, 'band') || null, closestTo(rowEl, '.session-sidebar-panel'))) return false;
    const label = (rowEl.querySelector('[data-row-name]')?.textContent || '').trim() || name;
    announce(t('sidebar.row.wake_arm.armed', { name: label }));
    return true;
}

export async function wakeFromArm(ctrl: RowController, rowEl: Element): Promise<void> {
    if (wakeArm.busy || Date.now() - wakeArm.armedAt < ARM_GRACE_MS) return;
    const { name, band } = wakeArm;
    wakeArm.busy = true;
    try {
        await performWake(ctrl, rowEl);
    } finally {
        wakeArm.busy = false;
        disarmWake();
        const still = document.querySelector(`.session-sidebar-row[data-name="${CSS.escape(name)}"][data-asleep="1"]`);
        if (still) refocusRow(name, band);
    }
}

function openLayoutMember(ctrl: RowController, rowEl: Element): boolean {
    const band = dataOf(rowEl, 'band');
    if (band.indexOf('layout:') !== 0) return false;
    const open = rg().CloudeWeb?.layoutPage?.openLayout;
    if (typeof open !== 'function') return false;
    const sessionUuid = dataOf(rowEl, 'sessionUuid');
    if (!sessionUuid) return false;
    void open(band.slice('layout:'.length), sessionUuid);
    ctrl._closeAfterSwitch?.();
    return true;
}

async function markActiveRowRead(name: string): Promise<void> {
    try {
        await rg().API?.setSessionUnread(name, false);
    } catch (err) {
        console.error('SessionSidebar: mark read on the active row failed:', err);
    }
}

export async function activateRow(ctrl: RowController, rowEl: Element): Promise<void> {
    const g = rg();
    const name = dataOf(rowEl, 'name');
    if (!name) return;
    if (dataOf(rowEl, 'asleep') === '1') return;
    if (dataOf(rowEl, 'closed') === '1') return;
    if (dataOf(rowEl, 'archived') === '1') return;
    if (activateBrowserRow(ctrl, name)) return;
    if (g.SessionSidebarLayouts?.activate?.(ctrl, name)) return;
    if (openLayoutMember(ctrl, rowEl)) return;
    const NG = g.NavigationGeneration;
    if (ctrl._pendingSelection?.name === name && (!NG || NG.isCurrent(ctrl._pendingSelection.nav))) return;
    if (name === ctrl._activeTmuxName && !ctrl._pendingSelection && g.CloudeWeb?.browsers?.showing?.()) {
        g.CloudeWeb.browsers.dismiss?.();
        ctrl._closeAfterSwitch?.();
        return;
    }
    const onHome = g.App?.currentScreen === 'launchpad';
    if (name === ctrl._activeTmuxName && !ctrl._pendingSelection && !onHome) {
        closeMenuPagesExcept(null);
        ctrl._closeAfterSwitch?.();
        void markActiveRowRead(name);
        return;
    }
    const sessionId = dataOf(rowEl, 'sessionId') || null;
    if (sessionId && await g.SoloWindow?.focusIfOpen?.(sessionId)) return;
    const nav: NavToken = NG ? NG.begin(`session:${name}`) : null;
    const stillOurs = (): boolean => !NG || NG.keep(nav, `sidebar switch to ${name}`);
    ctrl._pendingSelection = { name, nav };
    paintSelection(ctrl);
    try {
        const api = g.API;
        if (!api) throw new Error('the API client is not loaded');
        if (sessionId) {
            const info = await api.getSession(sessionId, { includeScrollback: true, parallelHistory: true });
            if (!stillOurs()) return;
            if (info) {
                ctrl._closeAfterSwitch?.();
                await g.App?.returnToExistingTerminal(info);
            }
            return;
        }
        const response = await api.adoptSession(name, true);
        if (!stillOurs()) return;
        const session = (response && response.session) || response;
        ctrl._closeAfterSwitch?.();
        window.dispatchEvent(new CustomEvent('session-created', {
            detail: {
                session,
                initialScrollbackB64: response.initial_scrollback_b64 || '',
                fifoStartOffset: typeof response.fifo_start_offset === 'number' ? response.fifo_start_offset : null,
                adopted: true,
            },
        }));
    } catch (err) {
        if (!stillOurs()) return;
        console.error('SessionSidebar: switch failed:', err);
        const e = err as { message?: string } | null;
        alert(t('sidebar.row.switch.failed', { detail: (e && e.message) || String(err) }));
    } finally {
        if (ctrl._pendingSelection?.nav === nav) {
            ctrl._pendingSelection = null;
            paintSelection(ctrl);
        }
    }
}

export async function runRowAction(ctrl: RowController, btnEl: Element): Promise<void> {
    const g = rg();
    const actions = g.SessionRowActions;
    if (!actions) return;
    const name = btnEl.getAttribute(actions.ATTR_NAME);
    if (!name) return;
    const action = btnEl.getAttribute(actions.ATTR_ACTION) || actions.ACTION_CLOSE;
    const rowEl = closestTo(btnEl, '.session-sidebar-row')
        || document.querySelector(`.session-sidebar-row[data-name="${CSS.escape(name)}"]`);
    if (action === actions.ACTION_RESTART) {
        await runRestartFlow(ctrl, name, rowEl);
        return;
    }
    if (!(rowEl && dataOf(rowEl, 'active') === '1') && !(await actions.confirm(action, name))) return;
    await closeLiveRow(ctrl, name, rowEl, action);
}

export async function closeLiveRow(ctrl: RowController, name: string, rowEl: Element | null, action: string): Promise<void> {
    const g = rg();
    if (rowEl && dataOf(rowEl, 'active') === '1') {
        ctrl._closeAfterSwitch?.();
        await g.TerminalController?.destroySession(action);
        return;
    }
    try {
        const sessionId = rowEl ? dataOf(rowEl, 'sessionId') || null : null;
        if (sessionId) await g.API?.destroySession(sessionId);
        else await g.API?.destroyExternalSession(name);
        await ctrl._fetchAndRender?.();
    } catch (err) {
        console.error(`SessionSidebar: ${action} failed:`, err);
        const e = err as { message?: string } | null;
        alert(t('sidebar.row.action.failed', { action, detail: (e && e.message) || String(err) }));
    }
}

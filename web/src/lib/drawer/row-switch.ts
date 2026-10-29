import { t } from '../i18n/index.svelte';
import { activate as activateBrowserRow } from './browser-rows';
import { clickEnv, messageOf, type ClickCtrl, type RowLike } from './click-env';

const SESSION_CREATED_EVENT = 'session-created';

export function paintSelection(ctrl: ClickCtrl): void {
    const env = clickEnv();
    const shell = env.CloudeWeb?.sidebarShell;
    if (shell && typeof shell.drew === 'function' && shell.drew(ctrl && ctrl.listEl)) {
        shell.paintSelection(ctrl);
        return;
    }
    const pending = ctrl._pendingSelection;
    const current = pending && (!env.NavigationGeneration || env.NavigationGeneration.isCurrent(pending.nav));
    let name: string | null;
    if (pending && current) {
        name = pending.name;
    } else {
        const layoutPage = env.CloudeWeb?.layoutPage;
        const openLayout = layoutPage && typeof layoutPage.isActive === 'function' && layoutPage.isActive()
            && typeof layoutPage.current === 'function' ? layoutPage.current() : null;
        const showing = env.CloudeWeb?.browsers;
        const browser = showing && typeof showing.showing === 'function' ? showing.showing() : null;
        name = openLayout ? `layout:${openLayout.uuid}` : (browser ? `browser:${browser}` : ctrl._activeTmuxName);
    }
    for (const row of ctrl.listEl?.querySelectorAll<HTMLElement>('.session-sidebar-row') || []) {
        row.setAttribute('aria-selected', row.dataset.name === name ? 'true' : 'false');
    }
}

function alreadyPending(ctrl: ClickCtrl, name: string): boolean {
    const pending = ctrl._pendingSelection;
    if (pending?.name !== name) return false;
    const nav = clickEnv().NavigationGeneration;
    return !nav || nav.isCurrent(pending.nav);
}

function handledWithoutSwitch(ctrl: ClickCtrl, rowEl: RowLike, name: string): boolean {
    const env = clickEnv();
    if (rowEl.dataset.asleep === '1') return true;
    if (activateBrowserRow(ctrl, name)) return true;
    if (env.SessionSidebarLayouts?.activate(ctrl, name)) return true;
    if (alreadyPending(ctrl, name)) return true;
    if (name === ctrl._activeTmuxName && !ctrl._pendingSelection && !(env.App && env.App.currentScreen === 'launchpad')) {
        ctrl._closeAfterSwitch();
        return true;
    }
    return false;
}

async function adoptAndAnnounce(ctrl: ClickCtrl, name: string, stillOurs: () => boolean): Promise<void> {
    const response = await clickEnv().API!.adoptSession(name, true);
    if (!stillOurs()) return;
    const session = response.session || response;
    ctrl._closeAfterSwitch();
    window.dispatchEvent(new CustomEvent(SESSION_CREATED_EVENT, {
        detail: {
            session,
            initialScrollbackB64: response.initial_scrollback_b64 || '',
            fifoStartOffset: typeof response.fifo_start_offset === 'number' ? response.fifo_start_offset : null,
            adopted: true,
        },
    }));
}

export async function activateRow(ctrl: ClickCtrl, rowEl: Element | null): Promise<void> {
    const row = rowEl as RowLike | null;
    const name = row && row.dataset.name;
    if (!row || !name || handledWithoutSwitch(ctrl, row, name)) return;
    const env = clickEnv();
    const sessionId = row.dataset.sessionId || null;
    if (sessionId && env.SoloWindow && await env.SoloWindow.focusIfOpen(sessionId)) return;
    const nav = env.NavigationGeneration ? env.NavigationGeneration.begin('session:' + name) : null;
    const stillOurs = (): boolean => !env.NavigationGeneration || env.NavigationGeneration.keep(nav, 'sidebar switch to ' + name);
    ctrl._pendingSelection = { name, nav };
    paintSelection(ctrl);
    try {
        if (sessionId) {
            const info = await env.API!.getSession(sessionId, {
                includeScrollback: true, parallelHistory: true, scrollbackLines: env.CloudeTerminal!.SCROLLBACK_ROWS,
            });
            if (!stillOurs()) return;
            if (info) {
                ctrl._closeAfterSwitch();
                await env.App!.returnToExistingTerminal(info);
            }
            return;
        }
        await adoptAndAnnounce(ctrl, name, stillOurs);
    } catch (err) {
        if (!stillOurs()) return;
        console.error('SessionSidebar: switch failed:', err);
        window.alert(t('sidebar.row.switch.failed', { detail: messageOf(err) }));
    } finally {
        if (ctrl._pendingSelection?.nav === nav) {
            ctrl._pendingSelection = null;
            paintSelection(ctrl);
        }
    }
}

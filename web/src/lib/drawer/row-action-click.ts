import { t } from '../i18n/index.svelte';
import { clickEnv, messageOf, type ClickCtrl } from './click-env';
import { runRestart } from './restart-click';

function rowOf(btnEl: Element, name: string): HTMLElement | null {
    return btnEl.closest<HTMLElement>('.session-sidebar-row')
        || document.querySelector<HTMLElement>(`.session-sidebar-row[data-name="${CSS.escape(name)}"]`);
}

export async function onRowActionClick(ctrl: ClickCtrl, btnEl: Element): Promise<void> {
    const env = clickEnv();
    const actions = env.SessionRowActions;
    if (!actions) return;
    const name = btnEl.getAttribute(actions.ATTR_NAME);
    if (!name) return;
    const action = btnEl.getAttribute(actions.ATTR_ACTION) || actions.ACTION_CLOSE;
    const rowEl = rowOf(btnEl, name);
    if (action === actions.ACTION_RESTART) {
        await runRestart(ctrl, name, rowEl);
        return;
    }
    if (rowEl && rowEl.dataset.active === '1') {
        ctrl._closeAfterSwitch();
        await env.TerminalController!.destroySession(action);
        return;
    }
    if (!await actions.confirm(action, name)) return;
    try {
        const sessionId = rowEl ? (rowEl.dataset.sessionId || null) : null;
        if (sessionId) await env.API!.destroySession(sessionId);
        else await env.API!.destroyExternalSession(name);
        ctrl._lastSig = null;
        await ctrl._fetchAndRender();
    } catch (err) {
        console.error(`SessionSidebar: ${action} failed:`, err);
        window.alert(t('sidebar.row.action.failed', { action, detail: messageOf(err) }));
    }
}

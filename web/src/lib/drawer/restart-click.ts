import { t } from '../i18n/index.svelte';
import { drawerEnv } from './env';
import { sessionStore } from '../sessions/store.svelte';

interface RestartChoice {
    mode?: string;
    sessionUuid?: string;
    agentType?: string;
    account?: string;
    confirmRestartLive?: boolean;
}

interface RestartAsk {
    open(...args: unknown[]): Promise<RestartChoice | null>;
    lastError(): string | null;
}

interface RestartResult {
    ok?: boolean;
    status?: string;
    detail?: string;
    tmux_session?: string;
    session_id?: string | null;
    agent_type_persisted?: boolean;
    name?: string;
}

interface RestartCtrl {
    _lastSig?: string | null;
    _fetchAndRender?(): Promise<void>;
    _closeAfterSwitch?(): void;
}

interface RestartGlobals {
    Router?: { showError?(message: string): void };
    SessionRestartPicker?: RestartAsk;
    SessionRestartDirect?: RestartAsk;
    SessionRestartOptions?: { recreateTarget?(records: unknown, name: string): string | null };
    SessionRestartReturn?: { reopen(result: unknown): Promise<{ status: string; detail?: string }> };
    SessionKey?: { forName(name: string, hostKey: string | null | undefined): string | null };
    API?: {
        recreateSession(uuid: string | undefined, agentType?: string, account?: string): Promise<RestartResult>;
        respawnSession(target: string, agentType: string | undefined, confirmLive: boolean, account?: string): Promise<RestartResult>;
    };
}

function report(message: string): void {
    console.error('SessionSidebarRestartClick:', message);
    const router = (drawerEnv() as RestartGlobals).Router;
    if (router && typeof router.showError === 'function') router.showError(message);
}

async function resync(ctrl: RestartCtrl): Promise<void> {
    ctrl._lastSig = null;
    if (ctrl._fetchAndRender) await ctrl._fetchAndRender();
}

export async function runRestart(
    ctrl: RestartCtrl, name: string, rowEl: Element | null, hostKey?: string, focusWrapper?: boolean,
    armedByGesture?: boolean, busyWork?: boolean, direct?: boolean,
): Promise<void> {
    const g = drawerEnv() as RestartGlobals;
    const picker = g.SessionRestartPicker;
    if (!picker) {
        report(t('session.restart.error.picker_missing', { name }));
        return;
    }
    const trigger = (rowEl && typeof rowEl.querySelector === 'function' && rowEl.querySelector('[data-row-menu]'))
        || document.querySelector(`[data-row-menu="${CSS.escape(name)}"]`);
    const status = trigger ? trigger.getAttribute('data-row-menu-status') : null;
    let host = hostKey;
    if (!host && trigger && rowEl && rowEl.contains(trigger)) host = trigger.getAttribute('data-row-menu-host-key') || 'local';
    const nameEl = rowEl ? rowEl.querySelector('.session-sidebar-row-name') : null;
    const label = ((nameEl && nameEl.textContent) || '').trim() || name;
    const remote = !!host && host !== 'local';
    const target = g.SessionKey ? g.SessionKey.forName(name, host) : (remote ? null : name);
    if (!target) {
        report(t('session.restart.error.key_missing', { name }));
        return;
    }
    const opts = g.SessionRestartOptions;
    const uuid = !remote && opts && opts.recreateTarget ? opts.recreateTarget(sessionStore.sessionRecords, name) : null;
    const oneClick = direct === true ? g.SessionRestartDirect : null;
    const choice = oneClick
        ? await oneClick.open(target, label, status, uuid, busyWork === true)
        : await picker.open(target, label, status, uuid, !!focusWrapper, armedByGesture === true, busyWork === true);
    if (!choice) {
        const why = (oneClick || picker).lastError();
        if (why) report(t('session.restart.error.no_prediction', { name, reason: why }));
        return;
    }
    await act(ctrl, name, target, choice);
}

async function act(ctrl: RestartCtrl, name: string, target: string, choice: RestartChoice): Promise<void> {
    const g = drawerEnv() as RestartGlobals;
    const recreating = choice.mode === 'recreate';
    const verb = recreating ? 'recreate' : 'restart';
    let result: RestartResult | null = null;
    try {
        result = recreating
            ? await g.API!.recreateSession(choice.sessionUuid, choice.agentType, choice.account)
            : await g.API!.respawnSession(target, choice.agentType, choice.confirmRestartLive === true, choice.account);
    } catch (err) {
        console.error(`SessionSidebar: ${verb} failed:`, err);
        report(t('session.restart.error.' + verb, { name, detail: err instanceof Error ? err.message : String(err) }));
        await resync(ctrl);
        return;
    }
    const worked = recreating ? result && result.status === 'started' : result && result.ok === true;
    if (!worked || !result) {
        report(t('session.restart.error.' + verb, { name, detail: (result && result.detail) || t('session.restart.error.no_reason') }));
        await resync(ctrl);
        return;
    }
    if (recreating) {
        result = { name: result.tmux_session || name, session_id: result.session_id || null, detail: result.detail || '' };
    }
    if (!recreating && choice.agentType && result.agent_type_persisted === false) {
        report(t('session.restart.error.not_saved', { name, agent: choice.agentType }));
    }
    const back = g.SessionRestartReturn
        ? await g.SessionRestartReturn.reopen(result)
        : { status: 'not_reopened', detail: 'the reopen module did not load' };
    if (back.status === 'reopened') {
        if (ctrl._closeAfterSwitch) ctrl._closeAfterSwitch();
        return;
    }
    if (back.detail) report(back.detail);
    await resync(ctrl);
}

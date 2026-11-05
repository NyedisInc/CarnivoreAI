import { drawerEnv } from './env';
import { confirmOk } from '../confirm-ok/confirm-ok';
import type { SidebarPick } from '../legacy-globals';
import { say, tr } from '../item-menu/run/run-env';
import { nonEmptyErrorMessageOr } from '../errors/failure-reason';

export interface SleepCtx {
    name: string;
    label?: string;
    sessionUuid?: string;
    surface?: string;
}

interface WakeAnswer { status?: string; code?: string; detail?: string; session_id?: string | null }

export interface WakeOutcome { started: boolean; sessionId: string | null }

interface PickerChoice { agentType?: string; account?: string }

interface SleepGlobals {
    API?: {
        sleepSession(uuid: string): Promise<{ status?: string; detail?: string } | undefined>;
        wakeSession(uuid: string, agentType?: string | null, account?: string | null, startFresh?: boolean): Promise<WakeAnswer | undefined>;
        killAsleepSession(uuid: string): Promise<unknown>;
        restartSession(uuid: string): Promise<unknown>;
        deleteSessionRecord(uuid: string): Promise<unknown>;
    };
    SessionRestartPicker?: {
        open?(name: string, label: string, a: null, uuid: string): Promise<PickerChoice | null>;
        lastError?(): string | null;
    };
    SessionSidebar?: SidebarPick<'forceRefresh' | 'activeTmuxName'>;
    TerminalController?: {
        sessionActive?: boolean;
        stopReconnecting?(): void;
        ws?: { close(): void } | null;
        _intentionalClose?: boolean;
    };
    NavigationGeneration?: { begin(label: string): unknown };
    WakeFocus?: { afterWake(sessionUuid: string, nav: unknown): unknown };
}

/* pick a wrapper */
export const WRAPPER_NEEDED = 'wrapper_needed';

export const TRANSCRIPT_MISSING = 'transcript_missing';

function g(): SleepGlobals {
    return drawerEnv() as SleepGlobals;
}

async function refresh(): Promise<void> {
    const bar = g().SessionSidebar;
    if (bar && typeof bar.forceRefresh === 'function') await bar.forceRefresh();
}

function reasonOf(err: unknown): string {
    return nonEmptyErrorMessageOr(err, tr('error.server_unreachable'));
}

export function releaseThisTab(ctx: { name: string }): void {
    const tc = g().TerminalController;
    const bar = g().SessionSidebar;
    if (!tc || !bar || bar.activeTmuxName() !== ctx.name) return;
    tc.sessionActive = false;
    if (typeof tc.stopReconnecting === 'function') tc.stopReconnecting();
    if (tc.ws) {
        tc._intentionalClose = true;
        tc.ws.close();
        tc.ws = null;
    }
    window.dispatchEvent(new CustomEvent('cloude:primary-session-gone', { detail: { tmuxName: ctx.name } }));
}

export async function runSleep(ctx: SleepCtx): Promise<void> {
    const name = ctx.label || ctx.name;
    if (!ctx.sessionUuid) { say(ctx, tr('session.sleep.no_uuid')); return; }
    try {
        const res = await g().API!.sleepSession(ctx.sessionUuid);
        if (!res || res.status !== 'asleep') {
            say(ctx, tr('session.sleep.failed', { name, reason: (res && res.detail) || '' }));
        } else {
            releaseThisTab(ctx);
        }
    } catch (err) {
        console.error('[SessionRowMenuSleep] sleep failed:', err);
        say(ctx, tr('session.sleep.failed', { name, reason: reasonOf(err) }));
    }
    await refresh();
}

export async function offerFresh(name: string, label: string, sessionUuid: string): Promise<WakeAnswer | null> {
    const ok = await confirmOk({
        title: tr('session.wake.fresh.title'),
        message: tr('session.wake.fresh.question', { name: label || name }),
        details: tr('session.wake.fresh.details'),
        okLabel: tr('session.wake.fresh.confirm'),
        cancelLabel: tr('session.wake.fresh.cancel'),
    });
    if (!ok) return null;
    return (await g().API!.wakeSession(sessionUuid, null, null, true)) ?? null;
}

/* could not wake */
export async function pickAndWake(name: string, label: string, sessionUuid: string): Promise<WakeAnswer | null> {
    const picker = g().SessionRestartPicker;
    if (!picker || typeof picker.open !== 'function') return null;
    const choice = await picker.open(name, label, null, sessionUuid);
    if (!choice || !choice.agentType) return null;
    return (await g().API!.wakeSession(sessionUuid, choice.agentType, choice.account)) ?? null;
}

async function resolveRefusal(ctx: SleepCtx, name: string, res: WakeAnswer | undefined): Promise<WakeAnswer | undefined | 'cancelled'> {
    const picker = g().SessionRestartPicker;
    const uuid = ctx.sessionUuid as string;
    let answer = res;
    if (answer && answer.status === 'refused' && answer.code === WRAPPER_NEEDED && picker) {
        const picked = await pickAndWake(ctx.name, name, uuid);
        if (!picked) {
            const why = typeof picker.lastError === 'function' ? picker.lastError() : '';
            if (why) say(ctx, tr('session.wake.failed', { name, reason: why }));
            return 'cancelled';
        }
        answer = picked;
    }
    if (answer && answer.status === 'refused' && answer.code === TRANSCRIPT_MISSING) {
        answer = (await offerFresh(ctx.name, name, uuid)) || answer;
    }
    return answer;
}

export async function runWakeWithId(ctx: SleepCtx): Promise<WakeOutcome> {
    const name = ctx.label || ctx.name;
    let started = false;
    let sessionId: string | null = null;
    if (!ctx.sessionUuid) { say(ctx, tr('session.wake.no_uuid')); return { started: false, sessionId: null }; }
    const nav = g().NavigationGeneration ? g().NavigationGeneration!.begin('wake:' + ctx.name) : null;
    try {
        const res = await resolveRefusal(ctx, name, await g().API!.wakeSession(ctx.sessionUuid));
        if (res === 'cancelled') { await refresh(); return { started: false, sessionId: null }; }
        started = !!res && res.status === 'started';
        sessionId = (started && res && res.session_id) || null;
        if (!started) say(ctx, tr('session.wake.failed', { name, reason: (res && res.detail) || '' }));
    } catch (err) {
        console.error('[SessionRowMenuSleep] wake failed:', err);
        say(ctx, tr('session.wake.failed', { name, reason: reasonOf(err) }));
    }
    await refresh();
    if (started && g().WakeFocus) void g().WakeFocus!.afterWake(ctx.sessionUuid, nav);
    return { started, sessionId };
}

export async function runWake(ctx: SleepCtx): Promise<boolean> {
    return (await runWakeWithId(ctx)).started;
}

export async function runKillAsleep(ctx: SleepCtx): Promise<boolean> {
    const name = ctx.label || ctx.name;
    if (!ctx.sessionUuid) { say(ctx, tr('session.wake.no_uuid')); return false; }
    const ok = await confirmOk({
        title: tr('session.kill_asleep.title'),
        message: tr('session.kill_asleep.question', { name }),
        details: tr('session.kill_asleep.details'),
        okLabel: tr('session.kill_asleep.confirm'),
        cancelLabel: tr('session.kill_asleep.cancel'),
        variant: 'danger',
    });
    if (!ok) return false;
    let done = false;
    try {
        await g().API!.killAsleepSession(ctx.sessionUuid);
        done = true;
    } catch (err) {
        console.error('[SessionRowMenuSleep] kill asleep failed:', err);
        say(ctx, tr('session.kill_asleep.failed', { name, reason: reasonOf(err) }));
    }
    await refresh();
    return done;
}

export async function runReopen(ctx: SleepCtx): Promise<boolean> {
    const name = ctx.label || ctx.name;
    if (!ctx.sessionUuid) { say(ctx, tr('session.wake.no_uuid')); return false; }
    const nav = g().NavigationGeneration ? g().NavigationGeneration!.begin('reopen:' + ctx.name) : null;
    let started = false;
    try {
        await g().API!.restartSession(ctx.sessionUuid);
        started = true;
    } catch (err) {
        console.error('[SessionRowMenuSleep] reopen failed:', err);
        say(ctx, tr('session.reopen.failed', { name, reason: reasonOf(err) }));
    }
    await refresh();
    if (started && g().WakeFocus) void g().WakeFocus!.afterWake(ctx.sessionUuid, nav);
    return started;
}

export async function runArchive(ctx: SleepCtx): Promise<boolean> {
    if (!ctx.sessionUuid) { say(ctx, tr('session.archive.failed.no_id')); return false; }
    let done = false;
    try {
        await g().API!.deleteSessionRecord(ctx.sessionUuid);
        done = true;
    } catch (err) {
        console.error('[SessionRowMenuSleep] archive failed:', err);
        say(ctx, tr('session.archive.failed', { reason: reasonOf(err) }));
    }
    await refresh();
    return done;
}

export const rowMenuSleepGlobal = { runSleep, pickAndWake, offerFresh };

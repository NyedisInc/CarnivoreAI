import { beginEdit } from '../../drawer/rename';
import type { RowMenuCtx } from '../row-context';
import { runWakeWithId } from '../../drawer/row-menu-sleep';
import { nonEmptyErrorMessageOr } from '../../errors/failure-reason';
import { rowElementFor, runEnv, say, tr } from './run-env';

const FORK_WAKE_TIMEOUT_MS = 30_000;

export async function runRenamePrompt(ctx: RowMenuCtx, rowEl: Element | null): Promise<void> {
    const env = runEnv();
    const prompter = env.TextPromptModal;
    const renameId = ctx.sessionId || (ctx.asleep ? ctx.sessionUuid : '');
    if (!renameId || !prompter || typeof prompter.open !== 'function') {
        say(ctx, tr('session.menu.rename.no_id', { label: ctx.label || ctx.name }));
        return;
    }
    const nameEl = rowEl && rowEl.querySelector('[data-row-name]');
    const shownName = nameEl ? (nameEl.textContent || '').trim() : '';
    const seed = shownName || ctx.label || ctx.name || '';
    const asked = await prompter.open({
        title: tr('session.menu.rename.title'), label: tr('session.menu.rename.label'),
        defaultValue: seed, confirmLabel: tr('session.menu.rename.confirm'), cancelLabel: tr('session.menu.rename.cancel'),
    });
    const raw = asked === null ? '' : String(asked).trim();
    if (!raw || raw === seed) return;
    const verdict = env.SessionLabel && env.SessionLabel.validate
        ? env.SessionLabel.validate(raw)
        : { ok: false, reason: tr('session.menu.rename.rule_unavailable') };
    if (!verdict.ok) { say(ctx, verdict.reason || ''); return; }
    try {
        await env.API!.renameSession(renameId, verdict.value || '');
    } catch (error) {
        console.error('[SessionRowMenuActions] rename failed:', error);
        say(ctx, tr('session.menu.rename.failed', { detail: nonEmptyErrorMessageOr(error, tr('error.server_unreachable')) }));
    }
}

export async function runRename(ctx: RowMenuCtx): Promise<void> {
    const rowEl = rowElementFor(ctx);
    const shown = rowEl && (typeof rowEl.checkVisibility === 'function'
        ? rowEl.checkVisibility({ visibilityProperty: true })
        : (typeof rowEl.getClientRects !== 'function' || rowEl.getClientRects().length > 0));
    if (!shown) {
        await runRenamePrompt(ctx, rowEl);
        return;
    }
    beginEdit(rowEl);
}

interface PushedRow { tmux_session?: string | null; session_uuid?: string | null; session?: { id?: string } | null }

function liveSessionIdFor(name: string, uuid: string): string | null {
    const env = runEnv();
    if (env.ListingPush?.isLive()) {
        const rows = env.ListingPush.rows<PushedRow>('list') ?? [];
        const hit = rows.find((r) => r.tmux_session === name || (!!uuid && r.session_uuid === uuid));
        return hit?.session?.id ?? null;
    }
    const row = env.SessionSidebar?.rows().find((r) => !r.asleep && (r.name === name || r.session_uuid === uuid));
    return typeof row?.session_id === 'string' ? row.session_id : null;
}

async function waitForLiveSessionId(name: string, uuid: string): Promise<string | null> {
    const env = runEnv();
    const now = liveSessionIdFor(name, uuid);
    if (now) return now;
    const push = env.ListingPush;
    if (!push?.isLive()) {
        await env.SessionSidebar?.forceRefresh();
        return liveSessionIdFor(name, uuid);
    }
    return new Promise<string | null>((resolve) => {
        const finish = (id: string | null): void => { clearTimeout(timer); stop(); resolve(id); };
        const stop = push.onChange(() => { const id = liveSessionIdFor(name, uuid); if (id) finish(id); });
        const timer = setTimeout(() => finish(null), FORK_WAKE_TIMEOUT_MS);
    });
}

async function wakeForSessionId(ctx: RowMenuCtx): Promise<string | null> {
    if (!ctx.sessionUuid) return null;
    const { started, sessionId } = await runWakeWithId(ctx);
    if (!started) return null;
    return sessionId ?? waitForLiveSessionId(ctx.name, ctx.sessionUuid);
}

export async function runFork(ctx: RowMenuCtx): Promise<void> {
    const env = runEnv();
    const picker = env.CloudeWeb && env.CloudeWeb.openForkPicker;
    const sessionId = ctx.asleep ? await wakeForSessionId(ctx) : ctx.sessionId;
    if (!sessionId || typeof picker !== 'function') {
        say(ctx, env.CloudeI18n!.t('session.fork_to.unavailable'));
        return;
    }
    picker(sessionId, ctx.label || ctx.name);
}

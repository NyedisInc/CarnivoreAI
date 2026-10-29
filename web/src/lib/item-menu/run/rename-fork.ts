import { beginEdit } from '../../drawer/rename';
import type { RowMenuCtx } from '../row-context';
import { messageOf } from '../../drawer/click-env';
import { runWake } from '../../drawer/row-menu-sleep';
import { rowElementFor, runEnv, say, tr } from './run-env';

const FORK_WAKE_POLL_MS = 250;
const FORK_WAKE_MAX_POLLS = 120;

export async function runRenamePrompt(ctx: RowMenuCtx, rowEl: Element | null): Promise<void> {
    const env = runEnv();
    const prompter = env.TextPromptModal;
    const renameId = ctx.sessionId || (ctx.asleep ? ctx.sessionUuid : '');
    if (!renameId || !prompter || typeof prompter.open !== 'function') {
        say(ctx, tr('session.menu.run.rename_no_id', { label: ctx.label || ctx.name }));
        return;
    }
    const nameEl = rowEl && rowEl.querySelector('[data-row-name]');
    const shownName = nameEl ? (nameEl.textContent || '').trim() : '';
    const seed = shownName || ctx.label || ctx.name || '';
    const asked = await prompter.open({
        title: tr('session.menu.run.rename_prompt_title'), label: tr('session.menu.run.rename_prompt_label'),
        defaultValue: seed, confirmLabel: tr('session.menu.run.rename_prompt_confirm'), cancelLabel: tr('session.menu.run.rename_prompt_cancel'),
    });
    const raw = asked === null ? '' : String(asked).trim();
    if (!raw || raw === seed) return;
    const verdict = env.SessionLabel && env.SessionLabel.validate
        ? env.SessionLabel.validate(raw)
        : { ok: false, reason: tr('session.menu.run.label_rule_missing') };
    if (!verdict.ok) { say(ctx, verdict.reason || ''); return; }
    try {
        await env.API!.renameSession(renameId, verdict.value || '');
    } catch (error) {
        console.error('[SessionRowMenuActions] rename failed:', error);
        say(ctx, tr('session.menu.run.rename_failed', { message: messageOf(error) }));
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

function liveRowFor(uuid: string): { session_id?: string } | null {
    const rows = runEnv().SessionSidebar?._rows || [];
    for (const r of rows) {
        if (r && !r.asleep && r.session_uuid === uuid && r.session_id) return r;
    }
    return null;
}

async function wakeForSessionId(ctx: RowMenuCtx): Promise<string | null> {
    if (!ctx.sessionUuid) return null;
    if (!(await runWake(ctx))) return null;
    for (let i = 0; i < FORK_WAKE_MAX_POLLS; i++) {
        const live = liveRowFor(ctx.sessionUuid);
        if (live) return live.session_id || null;
        await new Promise<void>((resolve) => { setTimeout(resolve, FORK_WAKE_POLL_MS); });
    }
    return null;
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

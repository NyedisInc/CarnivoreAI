import { rowByName, runRowAction } from '../../drawer/row-action-click';
import { clickEnv, messageOf } from '../../drawer/click-env';
import { nonEmptyErrorMessageOr } from '../../errors/failure-reason';
import { commitAssignment } from '../../sidebar-shell/group-assign';
import { togglePinRow } from '../../sidebar-shell/row-reorder';
import type { RowMenuCtx } from '../row-context';
import { recordFor, runEnv, say, tr } from './run-env';

export function repaintSurface(_ctx?: unknown): void {
    runEnv().SessionSidebar?.repaint();
}

export async function runToggleMute(ctx: RowMenuCtx): Promise<void> {
    const env = runEnv();
    const menu = env.CloudeWeb && env.CloudeWeb.rowMenu;
    const was = !!ctx.muted;
    const want = !was;
    if (menu) menu.setMuteOverride(ctx.name, want);
    const record = await recordFor(ctx.name);
    if (!record || !record.session_uuid) {
        if (menu) menu.setMuteOverride(ctx.name, was);
        say(ctx, tr('session.menu.mute.no_record', { label: ctx.label || ctx.name }));
        return;
    }
    try {
        const res = await env.API!.call(
            `/sessions/records/${encodeURIComponent(record.session_uuid)}/notifications`,
            { method: 'PATCH', body: { muted: want } },
        );
        if (menu && res && typeof res.muted === 'boolean') menu.setMuteOverride(ctx.name, res.muted);
    } catch (error) {
        if (menu) menu.setMuteOverride(ctx.name, was);
        console.error('[SessionRowMenuActions] mute write failed:', error);
        say(ctx, tr(want ? 'session.menu.mute.failed' : 'session.menu.unmute.failed', {
            label: ctx.label || ctx.name,
            detail: nonEmptyErrorMessageOr(error, tr('error.server_unreachable')),
        }));
    }
    repaintSurface(ctx);
}

export async function runMarkRead(ctx: RowMenuCtx): Promise<void> {
    try {
        await runEnv().API!.setSessionUnread(ctx.name, false);
    } catch (error) {
        console.error('[SessionRowMenuActions] mark read failed:', error);
        say(ctx, tr('session.menu.mark_read.failed'));
    }
    repaintSurface(ctx);
}

export async function runReconnectMcp(ctx: RowMenuCtx): Promise<void> {
    if (!ctx.sessionId) {
        say(ctx, tr('mcp.reconnect_failed'));
        return;
    }
    try {
        await runEnv().API!.call(`/sessions/${encodeURIComponent(ctx.sessionId)}/mcp/reconnect`, { method: 'POST', body: {} });
    } catch (error) {
        console.error('[SessionRowMenuActions] mcp reconnect failed:', error);
        say(ctx, tr('session.menu.run.reconnect_failed_detail', { reason: tr('mcp.reconnect_failed'), message: messageOf(error) }));
    }
}

export async function runClose(ctx: RowMenuCtx): Promise<void> {
    const actions = runEnv().SessionRowActions;
    if (!actions) {
        console.error('[SessionRowMenuActions] SessionRowActions missing, refusing to act');
        return;
    }
    const ctrl = clickEnv().SessionSidebar;
    if (!ctrl) return;
    await runRowAction(ctrl, actions.ACTION_CLOSE, ctx.name, rowByName(ctx.name), ctx.sessionId);
}

export async function runRemoveFromGroup(ctx: RowMenuCtx): Promise<void> {
    await commitAssignment(ctx.name, null);
}

export async function runToggleKeepAwake(ctx: RowMenuCtx): Promise<void> {
    const store = runEnv().CloudeWeb?.autoSleep;
    if (!store || typeof store.setKeepAwake !== 'function') return;
    const kept = store.isKeptAwake(ctx.name);
    if (kept === null) return;
    await store.setKeepAwake(ctx.name, !kept);
}

export function runTogglePin(ctx: RowMenuCtx): void {
    togglePinRow(ctx.name);
}

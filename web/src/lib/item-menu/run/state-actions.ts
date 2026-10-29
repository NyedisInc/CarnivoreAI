import { onRowActionClick } from '../../drawer/row-action-click';
import { clickEnv, messageOf } from '../../drawer/click-env';
import { commitAssignment } from '../../sidebar-shell/group-assign';
import { togglePinRow } from '../../sidebar-shell/row-reorder';
import type { RowMenuCtx } from '../row-context';
import { recordFor, runEnv, say, tr } from './run-env';

export function repaintSurface(_ctx?: unknown): void {
    const bar = runEnv().SessionSidebar;
    if (bar && typeof bar.repaint === 'function') {
        bar._lastSig = null;
        bar.repaint();
    }
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
        say(ctx, tr('session.menu.run.mute_unknown_record', { label: ctx.label || ctx.name }));
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
        say(ctx, tr(want ? 'session.menu.run.mute_failed' : 'session.menu.run.unmute_failed', { label: ctx.label || ctx.name, message: messageOf(error) }));
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
    const btn = document.createElement('button');
    btn.setAttribute(actions.ATTR_ACTION, actions.ACTION_CLOSE);
    btn.setAttribute(actions.ATTR_NAME, ctx.name);
    await onRowActionClick(ctrl, btn);
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

export async function runTogglePin(ctx: RowMenuCtx): Promise<void> {
    togglePinRow(ctx.name);
}

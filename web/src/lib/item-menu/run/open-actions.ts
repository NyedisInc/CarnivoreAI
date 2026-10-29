import { runRestart as clickRunRestart } from '../../drawer/clicks';
import { openPickerFor } from '../../drawer/group-actions';
import type { RowMenuCtx } from '../row-context';
import { rowElementFor, runEnv, say, tr } from './run-env';
import { clickEnv } from '../../drawer/click-env';

function anchorFor(ctx: RowMenuCtx): Element | null {
    const rowEl = rowElementFor(ctx);
    return rowEl ? rowEl.querySelector('[data-row-menu]') : null;
}

/* and the three */
export async function runRestart(ctx: RowMenuCtx, armedByGesture?: boolean, busyWork?: boolean, direct?: boolean): Promise<void> {
    const rowEl = rowElementFor(ctx);
    if (!rowEl) {
        say(ctx, tr('session.menu.run.restart_row_gone', { label: ctx.label || ctx.name }));
        return;
    }
    const env = clickEnv();
    await clickRunRestart(env.SessionSidebar!, ctx.name, rowEl, ctx.hostKey, false, armedByGesture === true, busyWork === true, direct === true);
}

export function runMoveToGroup(ctx: RowMenuCtx): void {
    const anchor = anchorFor(ctx);
    if (!anchor) {
        say(ctx, tr('session.menu.run.file_row_gone', { label: ctx.label || ctx.name }));
        return;
    }
    openPickerFor(anchor, ctx.name);
}

export function runAddTo(ctx: RowMenuCtx): void {
    const bridge = runEnv().CloudeWeb?.addToMenu;
    if (!bridge) return;
    const anchor = anchorFor(ctx);
    if (!anchor) {
        say(ctx, tr('session.menu.run.file_row_gone', { label: ctx.label || ctx.name }));
        return;
    }
    if (ctx.kind === 'layout') {
        if (typeof bridge.openForLayout === 'function') bridge.openForLayout(anchor, ctx.layoutUuid);
        return;
    }
    if (typeof bridge.openForSession === 'function') bridge.openForSession(anchor, ctx.name, ctx.sessionUuid || null);
}

async function projectNameFor(ctx: RowMenuCtx): Promise<string | null> {
    const api = runEnv().API;
    if (ctx.projectId == null || !api || typeof api.getProjects !== 'function') return null;
    try {
        const projects = await api.getProjects();
        const hit = Array.isArray(projects) ? projects.find((p) => p && p.id === ctx.projectId) : null;
        return (hit && hit.name) || null;
    } catch (err) {
        console.error('[SessionRowMenuActions] could not read projects:', err);
        return null;
    }
}

export function runSendTo(ctx: RowMenuCtx): void {
    const bridge = runEnv().CloudeWeb?.sendTo;
    if (!bridge || !ctx.sessionUuid) return;
    const anchor = anchorFor(ctx);
    if (!anchor) return;
    bridge.openForSession(anchor, { sessionUuid: ctx.sessionUuid, name: ctx.label || ctx.name, projectName: () => projectNameFor(ctx) });
}

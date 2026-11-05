import type { RowMenuCtx } from '../row-context';
import { projectHomePathFor, recordFor, runEnv, say, tr } from './run-env';
import { worktreeForSession } from '../../worktree-cleanup/api';
import { openWorktreeCleanup } from '../../worktree-cleanup/open';

/* the home screen */
export async function runNewInFolder(ctx: RowMenuCtx): Promise<void> {
    const lp = runEnv().Launchpad;
    if (!lp || typeof lp.selectProject !== 'function') {
        say(ctx, tr('session.menu.new_here.launcher_missing'));
        return;
    }
    const record = await recordFor(ctx.name);
    if (!record) {
        say(ctx, tr('session.menu.new_here.no_record', { label: ctx.label || ctx.name }));
        return;
    }
    if (!record.working_dir) {
        say(ctx, tr('session.menu.new_here.no_folder', { label: ctx.label || ctx.name }));
        return;
    }
    const rowName = record.title || ctx.label || ctx.name;
    await lp.selectProject({
        name: rowName,
        path: record.working_dir,
        launch_from: { kind: 'session', name: rowName, pinned: !!runEnv().SessionSidebarArrangement?.isPinned?.(ctx.name) },
    });
}

export async function runNewTerminalHere(ctx: RowMenuCtx): Promise<void> {
    const web = runEnv().CloudeWeb?.launchpad;
    if (!web || typeof web.createConsoleSession !== 'function') {
        say(ctx, tr('session.menu.terminal.launcher_missing'));
        return;
    }
    const path = await projectHomePathFor(ctx);
    if (!path) {
        say(ctx, tr('session.menu.terminal.no_folder', { label: ctx.label || ctx.name }));
        return;
    }
    await web.createConsoleSession({ workingDir: path });
}

export function runSchedule(ctx: RowMenuCtx): void {
    const web = runEnv().CloudeWeb;
    if (!ctx.sessionUuid || !web || typeof web.scheduleThis !== 'function') {
        say(ctx, tr('session.menu.schedule.unavailable'));
        return;
    }
    web.scheduleThis({ kind: 'session', id: ctx.sessionUuid });
}

export async function runShowPath(ctx: RowMenuCtx): Promise<void> {
    const web = runEnv().CloudeWeb;
    if (!web || typeof web.showPath !== 'function') {
        say(ctx, tr('session.menu.show_path.unavailable'));
        return;
    }
    const record = await recordFor(ctx.name);
    const path = (record && record.working_dir) || await projectHomePathFor(ctx);
    if (!path) {
        say(ctx, tr('session.menu.show_path.no_folder', { label: ctx.label || ctx.name }));
        return;
    }
    await web.showPath(path, ctx.label || ctx.name);
}

export function runCopySessionId(ctx: RowMenuCtx): Promise<boolean> {
    const compat = runEnv().CopyCompat;
    if (!ctx.conversationId || !compat || typeof compat.copyText !== 'function') {
        say(ctx, tr('session.menu.copy_session_id.failed'));
        return Promise.resolve(false);
    }
    return compat.copyText(ctx.conversationId).then((res) => {
        if (!res || !res.ok) say(ctx, tr('session.menu.copy_session_id.failed'));
        return !!(res && res.ok);
    });
}

export function runRemoveWorktree(ctx: RowMenuCtx): void {
    const wt = worktreeForSession(ctx.sessionId, ctx.name);
    if (!wt) {
        say(ctx, runEnv().CloudeI18n!.t('worktree.cleanup.not_listed'));
        return;
    }
    void openWorktreeCleanup({ paths: [wt.path] });
}

export function runMoveToFolder(ctx: RowMenuCtx): void {
    const env = runEnv();
    const bridge = env.CloudeWeb?.moveToFolder;
    if (!bridge || !ctx.sessionUuid) {
        say(ctx, env.CloudeI18n!.t('session.move.unavailable'));
        return;
    }
    bridge.open({ sessionUuid: ctx.sessionUuid, name: ctx.label || ctx.name });
}

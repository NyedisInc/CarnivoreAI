import { runMenuItem as runLayoutMenuItem } from '../../drawer/layouts-menu';
import { runMenuItem as runBrowserMenuItem } from '../../drawer/browser-rows';
import type { RowMenuCtx } from '../row-context';
import { runNewInFolder, runNewTerminalHere, runSchedule, runShowPath, runCopySessionId, runMoveToFolder } from './folder-actions';
import { runAddTo, runMoveToGroup, runRestart, runSendTo } from './open-actions';
import { runFork, runRename } from './rename-fork';
import { runArchive, runKillAsleep, runReopen, runSleep, runWake } from '../../drawer/row-menu-sleep';
import { navToken, recordFor, rowElementFor, runEnv, say } from './run-env';
import {
    repaintSurface, runClose, runMarkRead, runReconnectMcp, runRemoveFromGroup, runToggleKeepAwake, runTogglePin, runToggleMute,
} from './state-actions';

export interface RunOptions {
    armedByGesture?: boolean;
}

export function runPluginItem(itemId: string, ctx: RowMenuCtx): Promise<boolean> {
    const bridge = runEnv().CloudeWeb?.rowMenu;
    if (!bridge || typeof bridge.runPlugin !== 'function') return Promise.resolve(false);
    return bridge.runPlugin(itemId, ctx);
}

function runOtherKind(itemId: string, ctx: RowMenuCtx): Promise<unknown> | null {
    if (ctx.kind === 'browser') {
        const ran = runBrowserMenuItem(itemId, ctx);
        if (ran) return ran;
    }
    if (ctx.kind === 'layout') {
        const ran = runLayoutMenuItem(itemId, ctx);
        if (ran) return ran;
    }
    return null;
}

function runRestartItem(itemId: string, ctx: RowMenuCtx, opts?: RunOptions): Promise<void> | null {
    if (itemId === 'restart') return runRestart(ctx);
    if (itemId === 'restart-now') {
        const rowMenu = runEnv().CloudeWeb?.rowMenu;
        if (!rowMenu || !rowMenu.shiftHeld()) return runRestart(ctx);
        return runRestart(ctx, false, false, true);
    }
    if (itemId === 'update-restart') return runRestart(ctx, !!(opts && opts.armedByGesture === true), ctx.updateBusy === true);
    return null;
}

function runSleepItem(itemId: string, ctx: RowMenuCtx): unknown {
    if (itemId === 'close' && ctx.asleep) return runKillAsleep(ctx);
    if (itemId === 'close') return runClose(ctx);
    if (itemId === 'sleep') return runSleep(ctx);
    if (itemId === 'wake') return runWake(ctx);
    if (itemId === 'reopen') return runReopen(ctx);
    if (itemId === 'archive') return runArchive(ctx);
    return null;
}

const SIMPLE_ITEMS = new Map<string, (ctx: RowMenuCtx) => unknown>(Object.entries({
    'rename': runRename,
    'move-to-group': runMoveToGroup,
    'add-to': runAddTo,
    'add-members': runAddTo,
    'send-to': runSendTo,
    'move-to-folder': runMoveToFolder,
    'remove-from-group': runRemoveFromGroup,
    'fork': runFork,
    'new-in-folder': runNewInFolder,
    'new-terminal-here': runNewTerminalHere,
    'show-path': runShowPath,
    'copy-session-id': runCopySessionId,
    'mute': runToggleMute,
    'mark-read': runMarkRead,
    'reconnect-mcp': runReconnectMcp,
    'schedule': runSchedule,
    'keep-awake': runToggleKeepAwake,
    'pin': runTogglePin,
}));

export async function run(itemId: string, ctx: RowMenuCtx | null | undefined, opts?: RunOptions): Promise<unknown> {
    if (!ctx) return undefined;
    const other = runOtherKind(itemId, ctx);
    if (other) return other;
    const simple = SIMPLE_ITEMS.get(itemId);
    if (simple) return simple(ctx);
    const restart = runRestartItem(itemId, ctx, opts);
    if (restart) return restart;
    const slept = runSleepItem(itemId, ctx);
    if (slept !== null) return slept;
    return runPluginItem(itemId, ctx);
}

export const runTable = {
    run, navToken, recordFor, rowElementFor, runRename, runRestart, runPluginItem, runMoveToGroup, runAddTo, runSendTo, runFork,
    runNewInFolder, runNewTerminalHere, runToggleMute, runSchedule, runCopySessionId, runClose, repaintSurface, say,
} as const;

export function publishRunTable(root: Record<string, unknown>): void {
    root.SessionRowMenuActions = runTable;
}

import { clickEnv, elementOf, type ClickCtrl, type ClickEnv } from './click-env';
import { onListClick as renameOnListClick } from './rename';
import { onRowActionClick } from './row-action-click';
import { claim as claimChrome } from './chrome-clicks';
import { openSubagents, openShare, openTimers, toggleKeepAwake } from '../sidebar-shell/row-controls';
import { tookClick } from '../sidebar-shell/row-drag';
import { onPinClick } from '../sidebar-shell/row-reorder';
import { activateRow, paintSelection } from './row-switch';
import { onKeyClick as onBrowserKeyClick } from './browser-rows';
import { runRestart as runRestartFlow } from './restart-click';

interface Claim {
    selector: string;
    run(env: ClickEnv, ctrl: ClickCtrl, el: Element): Promise<void> | void;
}

const CLAIMS: readonly Claim[] = [
    { selector: '[data-keep-awake-session]', run: (_env, ctrl, el) => toggleKeepAwake(ctrl, el) },
    {
        selector: '[data-share-session-id]',
        run: (_env, _ctrl, el) => openShare(el),
    },
    {
        selector: '[data-subagents-session-id]',
        run(_env, _ctrl, el) {
            openSubagents(el);
        },
    },
    {
        selector: '[data-timers-session-id]',
        run(_env, _ctrl, el) {
            openTimers(el);
        },
    },
];

function ownedBefore(env: ClickEnv, ctrl: ClickCtrl, e: MouseEvent): boolean {
    if (claimChrome(ctrl, e)) return true;
    const shell = env.CloudeWeb?.sidebarShell;
    if (shell && typeof shell.owns === 'function' && shell.owns(e.target)) return true;
    if (tookClick()) return true;
    if (renameOnListClick(e)) return true;
    const pin = elementOf(e.target)?.closest('[data-pin-session]');
    if (!pin) return false;
    onPinClick(e, pin);
    return true;
}

export async function onRowClick(ctrl: ClickCtrl, e: MouseEvent): Promise<void> {
    const env = clickEnv();
    if (ownedBefore(env, ctrl, e)) return;
    const target = elementOf(e.target);
    if (!target) return;
    for (const claim of CLAIMS) {
        const el = target.closest(claim.selector);
        if (!el) continue;
        e.stopPropagation();
        await claim.run(env, ctrl, el);
        return;
    }
    const browserKey = target.closest('[data-browser-row-action]');
    if (browserKey) {
        e.stopPropagation();
        await onBrowserKeyClick(browserKey);
        return;
    }
    const actionEl = env.SessionRowActions ? target.closest(`[${env.SessionRowActions.ATTR_ACTION}]`) : null;
    if (actionEl) {
        e.stopPropagation();
        await onRowActionClick(ctrl, actionEl);
        return;
    }
    const rowEl = target.closest<HTMLElement>('.session-sidebar-row');
    if (rowEl) await activateRow(ctrl, rowEl);
}

type RestartRest = [hostKey?: string, focusWrapper?: boolean, armedByGesture?: boolean, busyWork?: boolean, direct?: boolean];

export function runRestart(ctrl: ClickCtrl, name: string, rowEl: Element | null, ...rest: RestartRest): Promise<unknown> {
    return runRestartFlow(ctrl, name, rowEl, ...rest);
}

export { activateRow, paintSelection, onRowActionClick };

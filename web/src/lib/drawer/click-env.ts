import { drawerEnv } from './env';
import type { PendingSelection } from './controller';

export interface ClickCtrl {
    listEl: HTMLElement | null;
    _activeTmuxName: string | null;
    _pendingSelection: PendingSelection | null;
    repaint?: () => void;
    _closeAfterSwitch(): void;
    _fetchAndRender(): Promise<void>;
}

export interface NavGeneration {
    begin(label: string): unknown;
    isCurrent(token: unknown): boolean;
    keep(token: unknown, label: string): boolean;
}

export interface RowActionsGlobal {
    ATTR_ACTION: string;
    ATTR_NAME: string;
    ACTION_CLOSE: string;
    ACTION_RESTART: string;
    confirm(action: string, name: string): Promise<boolean>;
}

export interface ClickEnv {
    SessionSidebar?: ClickCtrl;
    CloudeWeb?: {
        sidebarShell?: { owns?(t: EventTarget | null): boolean; drew?(el: unknown): boolean; paintSelection(ctrl: ClickCtrl): void };
        layoutPage?: { isActive?(): boolean; current?(): { uuid: string } | null };
        browsers?: { showing?(): string | null };
    };
    SessionSidebarLayouts?: { activate(ctrl: ClickCtrl, name: string): boolean };
    SessionRowActions?: RowActionsGlobal;
    WriteFailureNotice?: { notify(key: string, params: Record<string, unknown>, opts: Record<string, unknown>): void };
    NavigationGeneration?: NavGeneration;
    SoloWindow?: { focusIfOpen(sessionId: string): Promise<boolean> };
    App?: { currentScreen?: string; returnToExistingTerminal(info: unknown): Promise<void> };
    CloudeTerminal?: { SCROLLBACK_ROWS: number };
    TerminalController?: { destroySession(action: string): Promise<void> };
    API?: {
        getSession(id: string, opts: Record<string, unknown>): Promise<unknown>;
        adoptSession(name: string, flag: boolean): Promise<{ session?: unknown; initial_scrollback_b64?: string; fifo_start_offset?: unknown }>;
        destroySession(id: string): Promise<unknown>;
        destroyExternalSession(name: string): Promise<unknown>;
    };
}

export function clickEnv(): ClickEnv {
    return drawerEnv() as ClickEnv;
}

export interface ClosestTarget { closest<E extends Element = Element>(selector: string): E | null }

export interface RowLike { dataset: DOMStringMap }

export function hasClosest(target: unknown): target is ClosestTarget {
    return typeof target === 'object' && target !== null && typeof (target as { closest?: unknown }).closest === 'function';
}

export function elementOf(target: EventTarget | null): ClosestTarget | null {
    return hasClosest(target) ? target : null;
}

export function messageOf(err: unknown): string {
    return err instanceof Error && err.message ? err.message : String(err);
}

export function notifyAgentFailure(name: string, key: string, err: unknown): void {
    const notice = clickEnv().WriteFailureNotice;
    if (!notice || typeof notice.notify !== 'function') {
        console.warn('SessionSidebar:', 'no failure notice module for:', key);
        return;
    }
    notice.notify(key, { detail: messageOf(err) }, { titleKey: 'notice.action_failed.title', surface: name, logPrefix: 'SessionSidebar:' });
}

export function drawerController(): ClickCtrl | null {
    return clickEnv().SessionSidebar ?? null;
}

import type { SidebarRow } from './legacy';

export type NavToken = unknown;

export interface PendingSelection {
    name: string;
    nav: NavToken;
}

export interface RowController {
    listEl?: Element | null;
    _rows?: SidebarRow[];
    _dragging?: boolean;
    _activeTmuxName?: string | null;
    _pendingSelection?: PendingSelection | null;
    repaint?(): void;
    setDragging?(on: boolean): void;
    _fetchAndRender?(): Promise<void>;
    _closeAfterSwitch?(): void;
    close?(): void;
}

export interface MoveResult {
    crossed: boolean;
    pinned: boolean;
}

export interface RowArrangement {
    isPinned(name: string): boolean;
    togglePin(name: string, visibleNames: string[]): boolean;
    move(name: string, delta: number, visibleNames: string[]): MoveResult | null;
    placeAt(name: string, pinned: boolean, beforeName: string | null, visibleNames: string[]): MoveResult | null;
    moveInBand?(band: string, name: string, delta: number, bandNames: string[]): unknown;
    placeInBand?(band: string, name: string, beforeName: string | null, bandNames: string[]): unknown;
}

export interface BandIntent {
    pinned: boolean;
    group?: string | null;
}

export interface RowGroupStore {
    isFilingBand(key: string): boolean;
    bandIntent(key: string): BandIntent;
    setOptimistic(name: string, group: string | null): string | null | undefined;
}

export interface RowApi {
    getSession(id: string, o: { includeScrollback: boolean; parallelHistory?: boolean }): Promise<unknown>;
    adoptSession(name: string, attach: boolean): Promise<Record<string, unknown>>;
    renameSession(id: string, value: string): Promise<unknown>;
    destroySession(id: string): Promise<unknown>;
    destroyExternalSession(name: string): Promise<unknown>;
    setSessionUnread(name: string, unread: boolean): Promise<unknown>;
}

export interface RowGlobals {
    SessionSidebar?: RowController;
    NavigationGeneration?: {
        begin(target: string): NavToken;
        isCurrent(token: NavToken): boolean;
        keep(token: NavToken, what: string): boolean;
    };
    API?: RowApi;
    App?: { returnToExistingTerminal(info: unknown): Promise<void>; currentScreen?: string };
    SoloWindow?: { focusIfOpen?(sessionId: string): Promise<boolean> };
    TerminalController?: { destroySession(action: string): Promise<void> };
    SessionSidebarArrangement?: RowArrangement;
    SessionSidebarGroupStore?: RowGroupStore;
    SessionSidebarStore?: { isBandOrderKey?(key: string): boolean };
    SessionSidebarGroupOrder?: { commitMemberOrder?(name: string): Promise<unknown> };
    SessionSidebarLayouts?: {
        activate?(ctrl: RowController, name: string): boolean;
        isLayoutName?(name: string): boolean;
        rename?(id: string, value: string): Promise<unknown>;
    };
    SessionRowActions?: {
        ATTR_ACTION: string;
        ATTR_NAME: string;
        ACTION_CLOSE: string;
        ACTION_RESTART: string;
        confirm(action: string, name: string): Promise<boolean>;
    };
    PreferenceBridge?: { read?(field: string, fallback: () => unknown): unknown };
    CloudeWeb?: {
        rowMenu?: { runCplug?(cplugId: string, ctx: Record<string, unknown>): Promise<unknown> };
        autoSleep?: {
            isKeptAwake(name: string): boolean | null;
            setKeepAwake(name: string, on: boolean): Promise<unknown>;
        };
        openSubagentList?(el: Element, id: string | null, name: string | null): unknown;
        openTimerList?(el: Element, id: string | null, name: string | null): unknown;
        tabDrag?: { begin(o: Record<string, unknown>): boolean };
        browsers?: { showing?(): string | null; dismiss?(): boolean };
        layoutPage?: {
            isActive?(): boolean;
            current?(): { uuid: string } | null;
            openLayout?(uuid: string, focusSession?: string): unknown;
            focusMember?(sessionUuid: string, keyboard?: boolean): boolean;
        };
    };
}

export function rg(): RowGlobals {
    return globalThis as unknown as RowGlobals;
}

export function drawer(): RowController | null {
    return rg().SessionSidebar || null;
}

export function listElement(): Element | null {
    return drawer()?.listEl || null;
}

export function closestTo(target: EventTarget | null, selector: string): Element | null {
    const el = target as Element | null;
    return el && typeof el.closest === 'function' ? el.closest(selector) : null;
}

export function dataOf(el: Element | null, key: string): string {
    return (el as HTMLElement | null)?.dataset?.[key] || '';
}

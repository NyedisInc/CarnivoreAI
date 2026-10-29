import { registerCellSearch, toggleCellSearch, cellSearchOpen } from '../../../lib/terminal-search/cell-search';
import { toggleTerminalSearch, terminalSearchIsOpen } from '../../../lib/terminal-search/mount-search';
import type { ControllerLike } from '../../../lib/terminal-search/search-host';
import { skillsDrawerOpen, toggleSkillsDrawer } from '../../../lib/session-skills/drawer.svelte';
import { filesDrawer, filesShowing, listenFileDrawer } from '../../../lib/right-drawer/files.svelte';

export interface TerminalActionContext {
    controller: ControllerLike;
    container: HTMLElement;
    /* file editor */
    overlay: HTMLElement | null;
}
export type TerminalAction = 'files' | 'search' | 'skills' | 'plugins';
const terminals = new Map<string, TerminalActionContext>();

export interface TerminalOverlayContext {
    slot: string;
    controller: ControllerLike;
    host: HTMLElement;
}
export type TerminalOverlayFactory = (context: TerminalOverlayContext) => () => void;
const overlayFactories = new Set<TerminalOverlayFactory>();
const overlayStops = new Map<string, Map<TerminalOverlayFactory, () => void>>();

function startOverlay(slot: string, factory: TerminalOverlayFactory): void {
    const context = terminals.get(slot);
    const stops = overlayStops.get(slot);
    if (!context || !stops || stops.has(factory)) return;
    stops.set(factory, factory({ slot, controller: context.controller, host: context.overlay ?? context.container }));
}

export function registerTerminalOverlay(factory: TerminalOverlayFactory): () => void {
    overlayFactories.add(factory);
    for (const slot of terminals.keys()) startOverlay(slot, factory);
    return () => {
        overlayFactories.delete(factory);
        for (const stops of overlayStops.values()) {
            stops.get(factory)?.();
            stops.delete(factory);
        }
    };
}

export function terminalContext(slot: string): TerminalActionContext | null {
    return terminals.get(slot) ?? null;
}

export function registerTerminalActions(
    slot: string, controller: ControllerLike, container: HTMLElement, primary = false,
    overlay: HTMLElement | null = container,
): () => void {
    const context = { controller, container, overlay };
    terminals.set(slot, context);
    overlayStops.set(slot, new Map());
    for (const factory of overlayFactories) startOverlay(slot, factory);
    const stopSearch = primary ? () => {} : registerCellSearch(slot, controller, container);
    return () => {
        if (terminals.get(slot) === context) {
            terminals.delete(slot);
            for (const stop of overlayStops.get(slot)?.values() ?? []) stop();
            overlayStops.delete(slot);
        }
        stopSearch();
    };
}

interface DrawerLoader {
    openWhenReady(
        anchor: HTMLElement, controller: ControllerLike, directory: string | null, host: HTMLElement | null,
    ): Promise<void> | void;
    closeDrawer?(): Promise<void> | void;
    retarget?(controller: ControllerLike, host: HTMLElement | null): void;
}

function drawerLoader(): DrawerLoader | undefined {
    return (globalThis as { ConfigEditorLoader?: DrawerLoader }).ConfigEditorLoader;
}

function scopeOf(action: TerminalAction): string | null {
    return action === 'files' ? null : action;
}

export function toolShowing(slot: string, action: TerminalAction): boolean {
    if (action === 'search') return cellSearchOpen(slot) ?? (terminalContext(slot) ? terminalSearchIsOpen() : false);
    if (action === 'skills') return skillsDrawerOpen(slot);
    return filesShowing(slot, scopeOf(action));
}

export function terminalAction(
    slot: string, action: TerminalAction, anchor: HTMLElement, showing?: boolean,
): void {
    const context = terminalContext(slot);
    if (!context) return;
    if (action === 'search') {
        if (!toggleCellSearch(slot)) toggleTerminalSearch();
        return;
    }
    if (action === 'skills') {
        const sessionId = context.controller._sessionId?.() ?? null;
        if (sessionId) toggleSkillsDrawer(slot);
        return;
    }
    listenFileDrawer();
    const loader = drawerLoader();
    const directory = scopeOf(action);
    if (showing ?? filesShowing(slot, directory)) {
        void loader?.closeDrawer?.();
        return;
    }
    filesDrawer.slot = slot;
    void loader?.openWhenReady(anchor, context.controller, directory, context.overlay);
}

export function retargetFiles(slot: string): boolean {
    const context = terminalContext(slot);
    const loader = drawerLoader();
    if (!context || !loader?.retarget) return false;
    loader.retarget(context.controller, context.overlay);
    if (filesDrawer.open) filesDrawer.slot = slot;
    return true;
}

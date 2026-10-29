import { drawerEnv } from './env';


export interface DrawerRepaintTarget {
    isOpen?: boolean;
    panel?: HTMLElement | null;
    repaint(): void;
    refreshNow?(): Promise<void> | undefined;
}

let controller: DrawerRepaintTarget | null = null;

export function setDrawerController(c: DrawerRepaintTarget | null): void {
    controller = c;
}

export function drawerController(): DrawerRepaintTarget | null {
    const g = (drawerEnv() as { SessionSidebar?: DrawerRepaintTarget }).SessionSidebar;
    if (g && typeof g.repaint === 'function') return g;
    return controller;
}

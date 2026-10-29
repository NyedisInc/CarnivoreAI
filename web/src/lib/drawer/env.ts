
export type DrawerEnv = Record<string, any>;

let env: DrawerEnv | null = null;

export function pageWindow(): DrawerEnv {
    const g = globalThis as unknown as { window?: DrawerEnv };
    return g.window && typeof g.window === 'object' ? g.window : (globalThis as unknown as DrawerEnv);
}

export function drawerEnv(): DrawerEnv {
    return env || pageWindow();
}

export function setDrawerEnv(next: DrawerEnv | null): void {
    env = next;
}

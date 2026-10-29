import { hostWindow } from '../sessions/env';

export type NavToken = unknown;

interface NavigationGenerationApi {
    begin(target: string): NavToken;
    current(): NavToken;
    keep(token: NavToken, what: string): boolean;
}

function navigationGeneration(): NavigationGenerationApi | null {
    const win = hostWindow() as unknown as
        | { NavigationGeneration?: NavigationGenerationApi }
        | undefined;
    const api = win?.NavigationGeneration;
    return api && typeof api.begin === 'function' ? api : null;
}

export function beginNav(target: string): NavToken {
    return navigationGeneration()?.begin(target) ?? null;
}

export function currentNav(): NavToken {
    return navigationGeneration()?.current() ?? null;
}

export function keepNav(token: NavToken, what: string): boolean {
    const api = navigationGeneration();
    if (!api) return true;
    return api.keep(token, what);
}

export function withNav(
    detail: Record<string, unknown>,
    nav: NavToken,
): Record<string, unknown> {
    return nav == null ? detail : { ...detail, nav };
}

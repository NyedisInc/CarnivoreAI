/* navigation generation */

export type Origin =
    | { readonly kind: 'drawer'; readonly tab: string }
    | { readonly kind: 'page'; readonly id: string }
    | { readonly kind: 'none' };

export interface OriginDeps {
    drawerTab: () => string | null;
    /* navigation generation */
    generation: () => number;
}

interface Entry {
    readonly page: string;
    readonly from: Origin;
    readonly gen: number;
}

const MAX_DEPTH = 8;

let stack: Entry[] = [];

const CLOSE_WINDOW_MS = 500;

let closedPage: { id: string; at: number } | null = null;

export function noteClosedPage(id: string): void {
    closedPage = { id, at: performance.now() };
}

export function recentlyClosedPage(): string | null {
    return closedPage && performance.now() - closedPage.at < CLOSE_WINDOW_MS ? closedPage.id : null;
}

let closed: { tab: string; at: number } | null = null;

export function noteDrawerClosed(tab: string): void {
    closed = { tab, at: performance.now() };
}

export function recentlyClosedTab(): string | null {
    return closed && performance.now() - closed.at < CLOSE_WINDOW_MS ? closed.tab : null;
}

export function recordOpen(page: string, previous: string | null, deps: OriginDeps): void {
    let from: Origin = { kind: 'none' };
    const tab = deps.drawerTab();
    if (tab !== null) from = { kind: 'drawer', tab };
    else if (previous && previous !== page) from = { kind: 'page', id: previous };
    if (from.kind !== 'page') stack = [];
    stack = [...stack.filter((e) => e.page !== page), { page, from, gen: deps.generation() }].slice(-MAX_DEPTH);
}

export function resolveBack(page: string, deps: OriginDeps): Origin {
    const top = stack[stack.length - 1];
    if (!top || top.page !== page) {
        stack = [];
        return { kind: 'none' };
    }
    stack = stack.slice(0, -1);
    if (top.gen !== deps.generation()) {
        stack = [];
        return { kind: 'none' };
    }
    return top.from;
}

export function clearOrigins(): void {
    stack = [];
    closed = null;
    closedPage = null;
}

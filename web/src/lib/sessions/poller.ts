/*  hidden  */

import { hostDocument, hostWindow } from './env';

export const POLL_INTERVAL_MS = 5000;

export interface PollerDeps {
    tick: () => Promise<unknown> | unknown;
    isAuthenticated?: () => boolean;
    shouldPoll?: () => boolean;
    setIntervalFn?: (handler: () => void, ms: number) => unknown;
    clearIntervalFn?: (handle: unknown) => void;
    intervalMs?: number;
    push?: { pushOrPoll(refresh: () => void, intervalMs: number, collections: readonly string[]): () => void } | null;
    pushCollections?: readonly string[];
}

export interface Poller {
    start(): void;
    stop(): void;
    readonly running: boolean;
}

export function defaultIsAuthenticated(): boolean {
    const auth = (hostWindow() as unknown as {
        Auth?: { isAuthenticated?: unknown };
    } | undefined)?.Auth;
    return !!(auth && typeof auth.isAuthenticated === 'function'
        && (auth.isAuthenticated as () => boolean)());
}

const SCREEN_ID = 'launchpad-screen';
const ACTIVE_CLASS = 'active';

export const VISIBLE = 'visible';
export const HIDDEN = 'hidden';
export const CANNOT_DETERMINE = 'cannot_determine';

/* CANNOT_DETERMINE */
export function launchpadVisibility(): string {
    const doc = hostDocument();
    const el = doc && typeof doc.getElementById === 'function'
        ? doc.getElementById(SCREEN_ID)
        : null;
    if (el && el.classList && typeof el.classList.contains === 'function') {
        return el.classList.contains(ACTIVE_CLASS) ? VISIBLE : HIDDEN;
    }
    const app = (hostWindow() as unknown as {
        App?: { currentScreen?: unknown };
    } | undefined)?.App;
    if (app && typeof app.currentScreen === 'string' && app.currentScreen) {
        return app.currentScreen === 'launchpad' ? VISIBLE : HIDDEN;
    }
    return CANNOT_DETERMINE;
}

export function defaultShouldPoll(): boolean {
    return launchpadVisibility() !== HIDDEN;
}

export function createPoller(deps: PollerDeps): Poller {
    const intervalMs = deps.intervalMs ?? POLL_INTERVAL_MS;
    const isAuthenticated = deps.isAuthenticated ?? defaultIsAuthenticated;
    const shouldPoll = deps.shouldPoll ?? defaultShouldPoll;
    const setIntervalFn = deps.setIntervalFn
        ?? ((h: () => void, ms: number) => setInterval(h, ms));
    const clearIntervalFn = deps.clearIntervalFn
        ?? ((handle: unknown) => clearInterval(handle as ReturnType<typeof setInterval>));

    let handle: unknown = null;

    return {
        get running(): boolean {
            return handle !== null;
        },
        start(): void {
            if (handle !== null) return;
            if (deps.push) {
                const gated = (): void => {
                    if (!isAuthenticated() || !shouldPoll()) return;
                    try {
                        Promise.resolve(deps.tick()).catch((err) => {
                            console.warn('CloudeWeb: running-sessions push tick failed:', err);
                        });
                    } catch (err) {
                        console.warn('CloudeWeb: running-sessions push tick failed:', err);
                    }
                };
                handle = { stopPush: deps.push.pushOrPoll(gated, intervalMs, deps.pushCollections ?? ['list', 'attachable', 'records']) };
                return;
            }
            handle = setIntervalFn(() => {
                if (!isAuthenticated()) return;
                if (!shouldPoll()) return;
                try {
                    Promise.resolve(deps.tick()).catch((err) => {
                        console.warn('CloudeWeb: running-sessions poll tick failed:', err);
                    });
                } catch (err) {
                    console.warn('CloudeWeb: running-sessions poll tick failed:', err);
                }
            }, intervalMs);
        },
        stop(): void {
            if (handle === null) return;
            const pushed = handle as { stopPush?: () => void };
            if (typeof pushed.stopPush === 'function') pushed.stopPush();
            else clearIntervalFn(handle);
            handle = null;
        },
    };
}

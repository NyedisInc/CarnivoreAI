import { afterEach, describe, expect, test } from 'vitest';

import {
    CANNOT_DETERMINE,
    createPoller,
    defaultIsAuthenticated,
    defaultShouldPoll,
    HIDDEN,
    launchpadVisibility,
    POLL_INTERVAL_MS,
    VISIBLE,
} from './poller';

function fakeTimer() {
    const state = {
        handlers: [] as Array<() => void>,
        intervals: [] as number[],
        cleared: [] as unknown[],
        nextHandle: 1,
    };
    return {
        state,
        setIntervalFn(handler: () => void, ms: number): unknown {
            state.handlers.push(handler);
            state.intervals.push(ms);
            return state.nextHandle++;
        },
        clearIntervalFn(handle: unknown): void {
            state.cleared.push(handle);
        },
        fire(): void {
            for (const h of state.handlers) h();
        },
    };
}

describe('starting and stopping', () => {
    test('start schedules exactly one interval, at 5 seconds', () => {
        const timer = fakeTimer();
        const p = createPoller({ tick: () => {}, ...timer });
        p.start();
        expect(timer.state.handlers).toHaveLength(1);
        expect(timer.state.intervals).toEqual([POLL_INTERVAL_MS]);
        expect(p.running).toBe(true);
    });

    test('a second start does not stack a second timer', () => {
        const timer = fakeTimer();
        const p = createPoller({ tick: () => {}, ...timer });
        p.start();
        p.start();
        p.start();
        expect(timer.state.handlers).toHaveLength(1);
    });

    test('STOP CLEARS THE INTERVAL, which launchpad.js never did', () => {
        const timer = fakeTimer();
        const p = createPoller({ tick: () => {}, ...timer });
        p.start();
        p.stop();
        expect(timer.state.cleared).toHaveLength(1);
        expect(p.running).toBe(false);
    });

    test('stop is idempotent and clears nothing extra', () => {
        const timer = fakeTimer();
        const p = createPoller({ tick: () => {}, ...timer });
        p.start();
        p.stop();
        p.stop();
        expect(timer.state.cleared).toHaveLength(1);
    });

    test('stop before start clears nothing and does not throw', () => {
        const timer = fakeTimer();
        createPoller({ tick: () => {}, ...timer }).stop();
        expect(timer.state.cleared).toEqual([]);
    });

    test('a stopped poller can be started again, with a fresh handle', () => {
        const timer = fakeTimer();
        const p = createPoller({ tick: () => {}, ...timer });
        p.start();
        p.stop();
        p.start();
        expect(timer.state.handlers).toHaveLength(2);
        expect(p.running).toBe(true);
    });
});

describe('the two gates', () => {
    test('a hidden launchpad screen does NOT poll', () => {
        let ticks = 0;
        const timer = fakeTimer();
        createPoller({
            tick: () => { ticks++; },
            isAuthenticated: () => true,
            shouldPoll: () => false,
            ...timer,
        }).start();
        timer.fire();
        timer.fire();
        timer.fire();
        expect(ticks).toBe(0);
    });

    test('a visible one DOES, which is what makes the count above evidence', () => {
        let ticks = 0;
        const timer = fakeTimer();
        createPoller({
            tick: () => { ticks++; },
            isAuthenticated: () => true,
            shouldPoll: () => true,
            ...timer,
        }).start();
        timer.fire();
        timer.fire();
        expect(ticks).toBe(2);
    });

    test('A SKIP IS NOT A STOP: the interval survives a hidden stretch', () => {
        let visible = false;
        let ticks = 0;
        const timer = fakeTimer();
        createPoller({
            tick: () => { ticks++; },
            isAuthenticated: () => true,
            shouldPoll: () => visible,
            ...timer,
        }).start();
        timer.fire();
        timer.fire();
        expect(ticks).toBe(0);
        visible = true;
        timer.fire();
        expect(ticks).toBe(1);
        expect(timer.state.cleared).toEqual([]);
    });

    test('a signed-out user does not poll either', () => {
        let ticks = 0;
        const timer = fakeTimer();
        createPoller({
            tick: () => { ticks++; },
            isAuthenticated: () => false,
            shouldPoll: () => true,
            ...timer,
        }).start();
        timer.fire();
        expect(ticks).toBe(0);
    });

    test('the auth gate is checked BEFORE the screen gate', () => {
        let screenAsked = 0;
        const timer = fakeTimer();
        createPoller({
            tick: () => {},
            isAuthenticated: () => false,
            shouldPoll: () => { screenAsked++; return true; },
            ...timer,
        }).start();
        timer.fire();
        expect(screenAsked).toBe(0);
    });

    test('a STOPPED poller cannot tick even if its handler is still held', () => {
        let ticks = 0;
        const timer = fakeTimer();
        const p = createPoller({
            tick: () => { ticks++; },
            isAuthenticated: () => true,
            shouldPoll: () => true,
            ...timer,
        });
        p.start();
        p.stop();
        expect(timer.state.cleared).toHaveLength(1);
        expect(p.running).toBe(false);
        expect(ticks).toBe(0);
    });
});

describe('a rejecting tick', () => {
    test('is caught, so one bad poll does not kill the timer', async () => {
        const timer = fakeTimer();
        const p = createPoller({
            tick: () => Promise.reject(new Error('probe failed')),
            isAuthenticated: () => true,
            shouldPoll: () => true,
            ...timer,
        });
        p.start();
        timer.fire();
        await Promise.resolve();
        await Promise.resolve();
        expect(p.running).toBe(true);
    });

    test('a THROWING tick is caught too, not only a rejecting one', async () => {
        const timer = fakeTimer();
        const p = createPoller({
            tick: () => { throw new Error('sync boom'); },
            isAuthenticated: () => true,
            shouldPoll: () => true,
            ...timer,
        });
        p.start();
        expect(() => timer.fire()).not.toThrow();
        await Promise.resolve();
        expect(p.running).toBe(true);
    });
});

describe('the default gates read the same globals the legacy tick read', () => {
    const planted = { window: false, document: false };

    function plant(props: Record<string, unknown>): void {
        const g = globalThis as Record<string, unknown>;
        if (!('window' in g)) { planted.window = true; g.window = {}; }
        if (!('document' in g)) { planted.document = true; g.document = { planted: true }; }
        Object.assign(g.window as Record<string, unknown>, props);
    }

    afterEach(() => {
        const g = globalThis as Record<string, unknown>;
        if (planted.window) { delete g.window; planted.window = false; }
        if (planted.document) { delete g.document; planted.document = false; }
    });

    test('NO WINDOW AT ALL is answered, not thrown', () => {
        expect(() => defaultIsAuthenticated()).not.toThrow();
        expect(() => defaultShouldPoll()).not.toThrow();
    });

    test('no auth layer means NOT signed in, so a booting page does not poll', () => {
        plant({});
        expect(defaultIsAuthenticated()).toBe(false);
    });

    test('an auth layer answering true is believed', () => {
        plant({ Auth: { isAuthenticated: () => true } });
        expect(defaultIsAuthenticated()).toBe(true);
    });

    test('an auth layer answering false is believed too', () => {
        plant({ Auth: { isAuthenticated: () => false } });
        expect(defaultIsAuthenticated()).toBe(false);
    });

    test('an Auth object with no isAuthenticated is not signed in', () => {
        plant({ Auth: {} });
        expect(defaultIsAuthenticated()).toBe(false);
    });


    function plantScreen(classes: string[] | null): void {
        const g = globalThis as Record<string, unknown>;
        plant({});
        (g.document as Record<string, unknown>).getElementById = (id: string) => {
            if (id !== 'launchpad-screen' || classes === null) return null;
            return { classList: { contains: (c: string) => classes.includes(c) } };
        };
    }

    test('the screen carrying `.active` is VISIBLE, and polls', () => {
        plantScreen(['screen', 'active']);
        expect(launchpadVisibility()).toBe(VISIBLE);
        expect(defaultShouldPoll()).toBe(true);
    });

    test('the screen WITHOUT `.active` is HIDDEN, and does not poll', () => {
        plantScreen(['screen']);
        expect(launchpadVisibility()).toBe(HIDDEN);
        expect(defaultShouldPoll()).toBe(false);
    });

    test('with no element, `App.currentScreen` is the same fact one level removed', () => {
        plantScreen(null);
        (globalThis as unknown as { window: Record<string, unknown> })
            .window.App = { currentScreen: 'terminal' };
        expect(launchpadVisibility()).toBe(HIDDEN);
        expect(defaultShouldPoll()).toBe(false);
        (globalThis as unknown as { window: Record<string, unknown> })
            .window.App = { currentScreen: 'launchpad' };
        expect(launchpadVisibility()).toBe(VISIBLE);
    });

    test('NEITHER READABLE IS `cannot_determine`, AND IT POLLS', () => {
        plantScreen(null);
        expect(launchpadVisibility()).toBe(CANNOT_DETERMINE);
        expect(defaultShouldPoll()).toBe(true);
    });

    test('an empty `currentScreen` string is not an answer either', () => {
        plantScreen(null);
        (globalThis as unknown as { window: Record<string, unknown> })
            .window.App = { currentScreen: '' };
        expect(launchpadVisibility()).toBe(CANNOT_DETERMINE);
    });

    test('the ELEMENT outranks `App.currentScreen`, because it is what the user sees', () => {
        plantScreen(['screen', 'active']);
        (globalThis as unknown as { window: Record<string, unknown> })
            .window.App = { currentScreen: 'terminal' };
        expect(launchpadVisibility()).toBe(VISIBLE);
    });
});

/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';

import { sessionStore } from '../sessions/store.svelte';
import { uiPrefs } from '../ui/prefs.svelte';
import { fixtureHost, fleet, settle, watchMutations } from './tree-harness';
import { mountList, type MountedList } from './running-harness';

const tick = () => sessionStore.loadRunningSessions((k: string) => k);

const TICKS_PER_WINDOW = 12;

let list: MountedList | null = null;

async function mountAndSettle(working: string[] = []): Promise<MountedList> {
    const mounted = mountList({});
    sessionStore.useHost(fixtureHost(fleet({ working })));
    await tick();
    await settle();
    return mounted;
}

beforeEach(() => {
    sessionStore.useHost(null);
    uiPrefs.resetForTests();
});

afterEach(() => {
    if (list) {
        list.destroy();
        list = null;
    }
});

describe('the real load path paints the list it is supposed to', () => {
    test('one tick through loadRunningSessions paints 45 rows', async () => {
        list = await mountAndSettle();
        expect(list.container.querySelectorAll('.running-session-row'))
            .toHaveLength(45);
    });

    test('and it paints them in the SORT order, newest created first', async () => {
        list = await mountAndSettle();
        const names = Array.from(
            list.container.querySelectorAll('.running-session-row'),
        ).map((el) => el.getAttribute('data-name'));
        expect(names[0]).toBe('cloude_p8_s4');
        expect(names.at(-1)).toBe('cloude_p0_s0');
    });
});

describe('TWELVE REAL TICKS with nothing changing cost the DOM nothing', () => {
    test('0 records and 0 nodes', async () => {
        list = await mountAndSettle();
        const watcher = watchMutations(list.container);
        for (let i = 0; i < TICKS_PER_WINDOW; i++) {
            await tick();
            await settle();
        }
        expect(watcher.stop()).toEqual({ records: 0, nodes: 0 });
    });

    test('and the row ORDER is unchanged after them, not merely restored', async () => {
        list = await mountAndSettle();
        const before = Array.from(
            list.container.querySelectorAll('.running-session-row'),
        ).map((el) => el.getAttribute('data-name'));
        for (let i = 0; i < TICKS_PER_WINDOW; i++) {
            await tick();
            await settle();
        }
        const after = Array.from(
            list.container.querySelectorAll('.running-session-row'),
        ).map((el) => el.getAttribute('data-name'));
        expect(after).toEqual(before);
        expect(after).toHaveLength(45);
    });

    test('NEGATIVE CONTROL: the list really is subscribed to these ticks', async () => {
        list = await mountAndSettle();
        const dot = () => list!.container.querySelector(
            '.running-session-row[data-name="cloude_p3_s2"] .status-dot',
        ) as HTMLElement;
        expect(dot().className).toContain('status-dot--idle');
        sessionStore.useHost(fixtureHost(fleet({ working: ['cloude_p3_s2'] })));
        await tick();
        await settle();
        expect(dot().className).toContain('status-dot--working');
    });
});

describe('a tick that DOES change one status is cheap and LOCAL', () => {
    test('the records are attributes only, and no node is added or removed', async () => {
        list = await mountAndSettle();
        const watcher = watchMutations(list.container);
        for (let i = 0; i < TICKS_PER_WINDOW; i++) {
            if (i === 5) {
                sessionStore.useHost(fixtureHost(fleet({ working: ['cloude_p3_s2'] })));
            }
            await tick();
            await settle();
        }
        const { records, nodes } = watcher.stop();
        expect(records).toBe(5);
        expect(nodes).toBe(0);
    });

    test('and the dot that changed is the SAME element it was before', async () => {
        list = await mountAndSettle();
        const sel = '.running-session-row[data-name="cloude_p3_s2"] .status-dot';
        const before = list.container.querySelector(sel);
        sessionStore.useHost(fixtureHost(fleet({ working: ['cloude_p3_s2'] })));
        await tick();
        await settle();
        expect(list.container.querySelector(sel)).toBe(before);
    });

    test('THE BUSY CASE: a status change lands while a rename editor is open', async () => {
        list = await mountAndSettle();
        const rowEl = list.container.querySelector(
            '.running-session-row[data-name="cloude_p3_s2"]',
        ) as HTMLElement;
        (rowEl.querySelector('.running-session-rename') as HTMLElement).click();
        await settle();
        const input = rowEl.querySelector(
            '.running-session-rename-input',
        ) as HTMLInputElement;
        input.value = 'half typed';
        sessionStore.useHost(fixtureHost(fleet({ working: ['cloude_p3_s2'] })));
        await tick();
        await settle();
        const after = rowEl.querySelector(
            '.running-session-rename-input',
        ) as HTMLInputElement;
        expect(after).toBe(input);
        expect(after.value).toBe('half typed');
        expect((rowEl.querySelector('.status-dot') as HTMLElement).className)
            .toContain('status-dot--working');
    });
});

describe('THE SOURCE RULE: nothing is published twice per tick', () => {
    async function loadRunningSessionsBody(): Promise<string> {
        const fs = await import('node:fs');
        const path = await import('node:path');
        const url = await import('node:url');
        const here = path.dirname(url.fileURLToPath(import.meta.url));
        const src = fs.readFileSync(
            path.join(here, '..', 'sessions', 'store.svelte.ts'), 'utf8');
        const start = src.indexOf('async function fetchRunningSessions');
        expect(start).toBeGreaterThan(-1);
        const body = src.slice(start);
        const method = body.slice(0, body.indexOf('\n}\n'));
        return method
            .replace(/\/\*[\s\S]*?\*\//g, ' ')
            .replace(/^[ \t]*\/\/.*$/gm, ' ');
    }

    test('the LISTING VERDICT is assigned once, and after the await', async () => {
        const method = await loadRunningSessionsBody();
        const assignments = method.match(/^\s*runningSessionsListing = /gm) || [];
        expect(assignments).toHaveLength(1);
        expect(method).toContain('runningSessionsListing = listing;');
        expect(method).not.toContain('runningSessionsListing = emptyListing()');
    });

    test('the ROW SET is still assigned once, and still the sorted one', async () => {
        const method = await loadRunningSessionsBody();
        const assignments = method.match(/^\s*runningSessions = /gm) || [];
        expect(assignments).toHaveLength(1);
        expect(method).toContain('runningSessions = sortRunningSessionsByWork');
    });

    test('TWELVE TICKS ON A FAILING PROBE cost the DOM nothing either', async () => {
        list = mountList({});
        const failing = {
            ...fixtureHost(fleet({})),
            listAttachableSessions: async () => {
                throw new Error('tmux did not answer');
            },
            listSessions: async () => {
                throw new Error('tmux did not answer');
            },
        };
        sessionStore.useHost(failing);
        await tick();
        await settle();
        expect(list.container.querySelector('.running-sessions-attention'))
            .not.toBeNull();
        const watcher = watchMutations(list.container);
        for (let i = 0; i < TICKS_PER_WINDOW; i++) {
            await tick();
            await settle();
        }
        expect(watcher.stop()).toEqual({ records: 0, nodes: 0 });
        expect(list.container.querySelector('.running-sessions-attention'))
            .not.toBeNull();
    });
});

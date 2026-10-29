/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';

import { sessionStore } from '../sessions/store.svelte';
import { uiPrefs } from '../ui/prefs.svelte';
import { settle } from './tree-harness';
import { mountList, row, type MountedList } from './running-harness';
import type { SessionHost } from '../sessions/host';
import type { AttachableSession } from '../sessions/types';

let list: MountedList | null = null;

const tick = () => sessionStore.loadRunningSessions((k: string) => k);

function hostWith(attachable: AttachableSession[]): SessionHost {
    return {
        getProjects: async () => [],
        getProjectsPresence: async () => ({ status: 'ok', projects: [] }),
        getProjectsAuthority: async () => ({ mode: 'db', degraded: false, writable: true }),
        listAttachableSessions: async () => attachable.map((r) => ({ ...r })),
        listSessions: async () => [],
        getCurrentSession: async () => null,
        listSessionRecords: async () => [],
    };
}

async function paint(attachable: AttachableSession[]): Promise<MountedList> {
    const mounted = mountList({});
    sessionStore.useHost(hostWith(attachable));
    await tick();
    await settle();
    return mounted;
}

function names(mounted: MountedList): (string | null)[] {
    return Array.from(mounted.container.querySelectorAll('.running-session-row'))
        .map((el) => el.getAttribute('data-name'));
}

const live = row('cloude_alpha', { status: 'idle', created_at_epoch: 1_700_000_000 });
const dead = row('cloude_ses_husk', { status: 'dead', created_at_epoch: 1_699_000_000 });
const murky = row('cloude_murky', { status: 'unknown', created_at_epoch: 1_698_000_000 });

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

describe('a DEAD pane is not a running session', () => {
    test('the husk is NOT rendered among the running rows', async () => {
        list = await paint([live, dead]);
        expect(names(list)).not.toContain('cloude_ses_husk');
    });

    test('and the live row IS still rendered, which proves it discriminates', async () => {
        list = await paint([live, dead]);
        expect(names(list)).toContain('cloude_alpha');
    });

    test('the heading count excludes the dead row', async () => {
        list = await paint([live, dead]);
        expect(list.chrome.counts.at(-1)?.text).toBe('session.running.count 1');
    });

    test('the STATE ARRAY itself drops it, not just the markup', async () => {
        list = await paint([live, dead]);
        expect(sessionStore.runningSessions.map((r) => r.name))
            .toEqual(['cloude_alpha']);
    });

    test('a listing of ONLY dead rows renders no rows at all', async () => {
        list = await paint([dead]);
        expect(names(list)).toEqual([]);
    });
});

describe('UNKNOWN is not a death', () => {
    test('a row whose status could not be read is KEPT and rendered', async () => {
        list = await paint([live, murky]);
        expect(names(list)).toContain('cloude_murky');
        expect(names(list)).toContain('cloude_alpha');
    });

    test('and it is counted, because it is still a session we hold', async () => {
        list = await paint([live, murky]);
        expect(list.chrome.counts.at(-1)?.text).toBe('session.running.count 2');
    });
});

describe('THE PARENT-LINK BADGE IS GONE from the running row', () => {
    test('the row id renders and no arrow to a predecessor does', async () => {
        list = mountList({
            rows: [row('cloude_api', { session_row_id: 7, parent_session_id: '4' })],
        });
        const badge = list.container.querySelector(
            '.running-session-id',
        ) as HTMLElement;
        expect(badge.textContent).toBe('#7');
        expect(list.container.innerHTML).not.toContain('←');
        expect(list.container.innerHTML).not.toContain('#4');
    });
});

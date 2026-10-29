import { beforeEach, describe, expect, test, vi } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { sessionStore } from '../sessions/store.svelte';
import {
    archiveSessionRecord,
    forkSession,
    isRestartInFlight,
    restartRecentSession,
    type RecentHost,
} from './recent-actions';
import { stateOf, type RecentSessionsPayload, type Translate } from './recent';

const i18n = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => i18n.t(key, params);

interface Recorder {
    host: RecentHost;
    fetched: boolean[];
    archived: string[];
    forked: string[];
    restarted: string[];
    created: Array<Record<string, string>>;
    errors: string[];
    refreshed: string[];
}

function recorder(overrides: {
    fetch?: RecentSessionsPayload | Error;
    archive?: unknown;
    fork?: unknown;
    restart?: unknown;
    create?: unknown;
} = {}): Recorder {
    const r: Recorder = {
        fetched: [], archived: [], forked: [], restarted: [], created: [],
        errors: [], refreshed: [],
        host: null as unknown as RecentHost,
    };
    const answer = <T,>(key: keyof typeof overrides, fallback: T): Promise<T> => {
        if (!(key in overrides)) return Promise.resolve(fallback);
        const value = overrides[key];
        return value instanceof Error
            ? Promise.reject(value)
            : Promise.resolve(value as T);
    };
    r.host = {
        fetchRecent(includeArchived) {
            r.fetched.push(includeArchived);
            return answer('fetch', { state: 'ok', sessions: [], notice: null });
        },
        archiveRecord(uuid) { r.archived.push(uuid); return answer('archive', {}); },
        fork(name) { r.forked.push(name); return answer('fork', {}) as Promise<never>; },
        restart(uuid) { r.restarted.push(uuid); return answer('restart', {}) as Promise<never>; },
        createSession(payload) { r.created.push(payload); return answer('create', {}); },
        showError(message) { r.errors.push(message); },
        async refreshRecent() { r.refreshed.push('recent'); },
        async refreshRunningSessions() { r.refreshed.push('running'); },
        async refreshAttribution() { r.refreshed.push('attribution'); },
        refreshProjectList() { r.refreshed.push('projects'); },
        liveSessions() { return []; },
        deriveDisplayName(name) { return name; },
    };
    return r;
}

beforeEach(() => {
    sessionStore.reset();
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
});

describe('the archive filter reaches the request, which is the whole defect', () => {
    test('the preference is passed, so archived records can reach a screen', async () => {
        const r = recorder();
        await sessionStore.refreshRecent(r.host.fetchRecent, true, t);
        expect(r.fetched).toEqual([true]);
    });

    test('with the preference off the request is unchanged', async () => {
        const r = recorder();
        await sessionStore.refreshRecent(r.host.fetchRecent, false, t);
        expect(r.fetched).toEqual([false]);
    });
});

describe('the store cannot turn a failure into an empty list', () => {
    test('a REJECTED fetch is recorded as probe_unavailable with a notice', async () => {
        const r = recorder({ fetch: new Error('network down') });
        await sessionStore.refreshRecent(r.host.fetchRecent, false, t);
        const payload = sessionStore.recentPayload;
        expect(stateOf(payload)).toBe('probe_unavailable');
        expect(payload?.sessions).toEqual([]);
        expect(payload?.notice).toBeTruthy();
        expect(payload?.notice).toContain('network down');
    });

    test('a rejection with no message still produces a notice', async () => {
        const r = recorder({ fetch: new Error('') });
        await sessionStore.refreshRecent(r.host.fetchRecent, false, t);
        expect(sessionStore.recentPayload?.notice).toBeTruthy();
    });

    test('a body with no state is recorded as probe_unavailable, never ok', async () => {
        const r = recorder({ fetch: {} as RecentSessionsPayload });
        await sessionStore.refreshRecent(r.host.fetchRecent, false, t);
        expect(stateOf(sessionStore.recentPayload)).toBe('probe_unavailable');
    });

    test('a reset store reads never_probed, never an empty ok', async () => {
        const r = recorder({ fetch: { state: 'ok', sessions: [] } });
        await sessionStore.refreshRecent(r.host.fetchRecent, false, t);
        expect(stateOf(sessionStore.recentPayload)).toBe('ok');
        sessionStore.reset();
        expect(sessionStore.recentPayload).toBeNull();
        expect(stateOf(sessionStore.recentPayload)).toBe('never_probed');
    });

    test('refreshRecent never rejects, whatever the fetch does', async () => {
        const r = recorder({ fetch: new Error('boom') });
        await expect(sessionStore.refreshRecent(r.host.fetchRecent, false, t))
            .resolves.toBeUndefined();
    });
});

describe('archiving is a soft archive and refreshes BOTH surfaces', () => {
    test('the uuid is what goes out, and both listings are re-read', async () => {
        const r = recorder();
        await archiveSessionRecord('a1b2-c3', r.host, t);
        expect(r.archived).toEqual(['a1b2-c3']);
        expect(r.refreshed).toEqual(['attribution', 'recent', 'projects']);
        expect(r.errors).toEqual([]);
    });

    test('no uuid says so rather than quietly doing nothing', async () => {
        const r = recorder();
        await archiveSessionRecord('', r.host, t);
        expect(r.archived).toEqual([]);
        expect(r.errors).toHaveLength(1);
        expect(r.refreshed).toEqual([]);
    });

    test('a failed archive reports and does NOT claim the row went away', async () => {
        const r = recorder({ archive: new Error('server said no') });
        await archiveSessionRecord('u1', r.host, t);
        expect(r.errors).toHaveLength(1);
        expect(r.errors[0]).toContain('server said no');
        expect(r.refreshed).toEqual([]);
    });
});

describe('forking surfaces three outcomes, not two', () => {
    test('a clean fork says nothing and refreshes', async () => {
        const r = recorder({ fork: { lineage_recorded: true } });
        await forkSession('cloude_work', r.host, t);
        expect(r.forked).toEqual(['cloude_work']);
        expect(r.errors).toEqual([]);
    });

    test('a 409 is reported as a REFUSAL, naming the missing conversation', async () => {
        const r = recorder({ fork: Object.assign(new Error('conflict'), { status: 409 }) });
        await forkSession('cloude_work', r.host, t);
        expect(r.errors).toHaveLength(1);
        expect(r.errors[0]).toMatch(/conversation/i);
        expect(r.refreshed).toEqual([]);
    });

    test('a fork whose parent link failed says so, not "done"', async () => {
        const r = recorder({ fork: { lineage_recorded: false } });
        await forkSession('cloude_work', r.host, t);
        expect(r.errors).toHaveLength(1);
        expect(r.refreshed).toContain('recent');
    });

    test("the server's own detail wins over the generic sentence", () => {
        const r = recorder({ fork: { lineage_recorded: false, detail: 'parent row 7 was gone' } });
        return forkSession('cloude_work', r.host, t).then(() => {
            expect(r.errors).toEqual(['parent row 7 was gone']);
        });
    });

    test('no session name says so rather than posting nothing', async () => {
        const r = recorder();
        await forkSession('', r.host, t);
        expect(r.forked).toEqual([]);
        expect(r.errors).toHaveLength(1);
    });
});

describe('restarting says what happened to the conversation, every time', () => {
    test('a clean resume says NOTHING, so a notice always means something', async () => {
        const r = recorder({ restart: { conversation: 'resumed', row_reused: true } });
        await restartRecentSession({ sessionUuid: 'u1' }, r.host, t);
        expect(r.restarted).toEqual(['u1']);
        expect(r.errors).toEqual([]);
        expect(r.refreshed).toEqual(['running', 'recent']);
    });

    test.each([
        ['none_recorded', /new conversation/i],
        ['unknown', /CANNOT BE DETERMINED/],
        [undefined, /CANNOT BE DETERMINED/],
    ])('conversation %s is said out loud', async (conversation, pattern) => {
        const r = recorder({ restart: { conversation } });
        await restartRecentSession({ sessionUuid: 'u1' }, r.host, t);
        expect(r.errors).toHaveLength(1);
        expect(r.errors[0]).toMatch(pattern);
    });

    test('a resumed restart that lost its row still gets a sentence', async () => {
        const r = recorder({ restart: { conversation: 'resumed', row_reused: false } });
        await restartRecentSession({ sessionUuid: 'u1' }, r.host, t);
        expect(r.errors).toHaveLength(1);
    });

    test('an empty response body is a third outcome, not a success', async () => {
        const r = recorder({ restart: null });
        await restartRecentSession({ sessionUuid: 'u1' }, r.host, t);
        expect(r.errors).toHaveLength(1);
        expect(r.errors[0]).toMatch(/did not say/);
    });

    test('a row with no uuid creates a session AND explains what it could not know', async () => {
        const r = recorder();
        await restartRecentSession(
            { title: 'Media', workingDir: '/p', agentType: 'claude' }, r.host, t,
        );
        expect(r.restarted).toEqual([]);
        expect(r.created).toEqual([{
            working_dir: '/p', agent_type: 'claude', project_name: 'Media',
        }]);
        expect(r.errors).toHaveLength(1);
        expect(r.errors[0]).toMatch(/CANNOT BE DETERMINED/);
    });

    test('a failed restart reports and does not claim a session came back', async () => {
        const r = recorder({ restart: new Error('tmux refused') });
        await restartRecentSession({ sessionUuid: 'u1' }, r.host, t);
        expect(r.errors).toHaveLength(1);
        expect(r.errors[0]).toContain('tmux refused');
        expect(r.refreshed).toEqual([]);
    });
});

describe('a double click restarts once, not twice (2026-09-24)', () => {
    test('a second click while the first is in flight never reaches the server', async () => {
        const r = recorder();
        let release: (v: unknown) => void = () => {};
        r.host.restart = (uuid) => {
            r.restarted.push(uuid);
            return new Promise<unknown>((resolve) => { release = resolve; }) as Promise<never>;
        };
        const first = restartRecentSession({ sessionUuid: 'u43' }, r.host, t);
        expect(isRestartInFlight({ sessionUuid: 'u43' })).toBe(true);
        await restartRecentSession({ sessionUuid: 'u43' }, r.host, t);
        expect(r.restarted).toEqual(['u43']);
        release({ conversation: 'resumed', row_reused: true });
        await first;
        expect(isRestartInFlight({ sessionUuid: 'u43' })).toBe(false);
        r.host.restart = (uuid) => { r.restarted.push(uuid); return Promise.resolve({}) as Promise<never>; };
        await restartRecentSession({ sessionUuid: 'u43' }, r.host, t);
        expect(r.restarted).toEqual(['u43', 'u43']);
    });

    test('a failed restart frees the row, and other rows are never held', async () => {
        const r = recorder({ restart: new Error('boom') });
        await restartRecentSession({ sessionUuid: 'u1' }, r.host, t);
        expect(isRestartInFlight({ sessionUuid: 'u1' })).toBe(false);
        let release: (v: unknown) => void = () => {};
        r.host.restart = (uuid) => {
            r.restarted.push(uuid);
            return new Promise<unknown>((resolve) => { release = resolve; }) as Promise<never>;
        };
        const held = restartRecentSession({ sessionUuid: 'a' }, r.host, t);
        r.host.restart = (uuid) => { r.restarted.push(uuid); return Promise.resolve({}) as Promise<never>; };
        await restartRecentSession({ sessionUuid: 'b' }, r.host, t);
        expect(r.restarted).toEqual(['u1', 'a', 'b']);
        release({});
        await held;
    });
});

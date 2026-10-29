import { beforeEach, describe, expect, test, vi } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { restartRecentSession, type RecentHost } from './recent-actions';
import { recentOpenStatus } from './recent-open-status.svelte';
import type { Translate } from './recent';

const i18n = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => i18n.t(key, params);

interface Rig {
    host: RecentHost;
    toasts: Array<Record<string, unknown>>;
    opened: Array<[string, string]>;
    errors: string[];
    settle: (value: unknown) => void;
    fail: (error: Error) => void;
}

function rig(): Rig {
    const r = { toasts: [], opened: [], errors: [] } as unknown as Rig;
    const pending = new Promise<unknown>((resolve, reject) => {
        r.settle = resolve;
        r.fail = reject;
    });
    r.host = {
        fetchRecent: async () => ({ state: 'ok', sessions: [], notice: null }),
        archiveRecord: async () => ({}),
        fork: async () => ({}),
        restart: () => pending as Promise<never>,
        createSession: async () => ({}),
        showError: (m) => { r.errors.push(m); },
        refreshRecent: async () => {},
        refreshRunningSessions: async () => {},
        refreshAttribution: async () => {},
        refreshProjectList: () => {},
        liveSessions: () => [],
        deriveDisplayName: (n) => n,
        toast: (record) => { r.toasts.push(record); },
        openSession: async (id, name) => { r.opened.push([id, name]); },
    };
    return r;
}

beforeEach(() => {
    recentOpenStatus.reset();
    vi.spyOn(console, 'error').mockImplementation(() => {});
});

describe('the row shows pending, then the result', () => {
    test('opening while out, then opened, a toast each, and the new session shown', async () => {
        const r = rig();
        const run = restartRecentSession({ sessionUuid: 'u1', title: 'api' }, r.host, t);
        expect(recentOpenStatus.of('u1')?.phase).toBe('opening');
        expect(r.toasts.map((x) => x.body)).toEqual(['opening api...']);
        r.settle({ conversation: 'resumed', row_reused: true, session: { id: 'ses_9', tmux_session: 'cloude_api' } });
        await run;
        expect(recentOpenStatus.of('u1')?.phase).toBe('opened');
        expect(r.toasts.map((x) => x.body)).toEqual(['opening api...', 'opened api']);
        expect(r.opened).toEqual([['ses_9', 'cloude_api']]);
        expect(r.errors).toEqual([]);
    });

    test('a refusal lands on the row and in a toast, in the server\'s own words', async () => {
        const r = rig();
        const refusal = 'agent failed to launch: /bin/zsh: no such option: name';
        const run = restartRecentSession({ sessionUuid: 'u2', title: 'Mini Terminal' }, r.host, t);
        expect(recentOpenStatus.of('u2')?.phase).toBe('opening');
        r.fail(new Error(refusal));
        await run;
        expect(recentOpenStatus.of('u2')).toEqual({ phase: 'failed', reason: refusal });
        expect(r.toasts.at(-1)?.body).toBe(`could not open Mini Terminal: ${refusal}`);
        expect(r.toasts.at(-1)?.local).toBe(true);
        expect(r.errors).toHaveLength(1);
        expect(r.errors[0]).toContain(refusal);
        expect(r.opened).toEqual([]);
    });
});

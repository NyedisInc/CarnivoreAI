import { beforeEach, describe, expect, test } from 'vitest';

import { findRunningSessionBySlug } from './deep-link';
import {
    DEEP_LINK_ATTEMPTS,
    attachRunningSession,
    isResolvingDeepLink,
    openProjectByName,
    resolveDeepLink,
    returnToActiveSession,
    selectProject,
} from './navigation';
import type { NavHost, SessionLike } from './nav-host';
import type { RunningSessionRow } from '../sessions/types';

const t = (key: string, params?: Record<string, unknown> | null): string =>
    params ? `${key}:${JSON.stringify(params)}` : key;

function row(patch: Partial<RunningSessionRow>): RunningSessionRow {
    return { name: 'cloude_a', label: null, ...patch } as RunningSessionRow;
}

interface Recorded {
    method: string;
    arg: unknown;
}

interface FakeHost extends NavHost {
    calls: Recorded[];
    rows: RunningSessionRow[];
    listingOk: boolean;
    adoptAnswer: Record<string, unknown>;
    createThrows: Error | null;
}

function fakeHost(patch: Partial<FakeHost> = {}): FakeHost {
    const calls: Recorded[] = [];
    const note = (method: string, arg: unknown = null) => calls.push({ method, arg });
    const host: FakeHost = {
        calls,
        rows: [],
        listingOk: true,
        adoptAnswer: {},
        createThrows: null,
        adoptSession: async (name, attach) => {
            note('adoptSession', { name, attach });
            return host.adoptAnswer;
        },
        getSession: async (id, options) => {
            note('getSession', { id, options });
            return { id } as SessionLike;
        },
        detachSession: async () => {
            note('detachSession');
            return null;
        },
        createSession: async (payload) => {
            note('createSession', payload);
            if (host.createThrows) throw host.createThrows;
            return { id: 'ses_new' } as SessionLike;
        },
        createProject: async (r) => {
            note('createProject', r);
            return null;
        },
        chooseProvider: async () => {
            note('chooseProvider');
            return {};
        },
        terminalDims: () => ({ cols: 80, rows: 24 }),
        reloadProjects: async () => {
            note('reloadProjects');
            return null;
        },
        reloadRunningSessions: async () => {
            note('reloadRunningSessions');
            return null;
        },
        runningSessions: () => host.rows,
        runningListingOk: () => host.listingOk,
        runningListingReason: () => 'probe_unavailable',
        announceSessionCreated: (detail) => note('announceSessionCreated', detail),
        rejectTarget: (name) => {
            note('rejectTarget', name);
            return true;
        },
        prepareTerminal: async () => {
            note('prepareTerminal');
            return { cols: 80, rows: 24 };
        },
        returnToExistingTerminal: (s) => note('returnToExistingTerminal', s),
        wait: async () => {},
        ...patch,
    };
    return host;
}

const methods = (host: FakeHost): string[] => host.calls.map((c) => c.method);

describe('the slug matcher', () => {
    test('resolves the cloude_ prefix stripped, exactly', () => {
        const rows = [row({ name: 'cloude_api' }), row({ name: 'cloude_web' })];
        expect(findRunningSessionBySlug(rows, 'api')?.name).toBe('cloude_api');
    });

    test('falls back to case-insensitive, then to the label, then to its case', () => {
        const rows = [
            row({ name: 'cloude_API' }),
            row({ name: 'cloude_x', label: 'Refactor spike (round 2)' }),
        ];
        expect(findRunningSessionBySlug(rows, 'api')?.name).toBe('cloude_API');
        expect(findRunningSessionBySlug(rows, 'Refactor spike (round 2)')?.name).toBe('cloude_x');
        expect(findRunningSessionBySlug(rows, 'refactor SPIKE (round 2)')?.name).toBe('cloude_x');
    });

    test('NEGATIVE CONTROL: a miss is null, and an empty target matches nothing', () => {
        const rows = [row({ name: 'cloude_api', label: 'api' })];
        expect(findRunningSessionBySlug(rows, 'nope')).toBe(null);
        expect(findRunningSessionBySlug(rows, '')).toBe(null);
        expect(findRunningSessionBySlug([], 'api')).toBe(null);
        expect(findRunningSessionBySlug(null, 'api')).toBe(null);
    });
});

describe('a listing that did not run is not an empty listing', () => {
    test('an UNREADABLE listing is re-asked, up to the bound', async () => {
        const host = fakeHost({ listingOk: false });
        expect(await resolveDeepLink('api', host)).toBe(null);
        expect(methods(host).filter((m) => m === 'reloadRunningSessions')).toHaveLength(
            DEEP_LINK_ATTEMPTS,
        );
    });

    test('a listing that RAN and found nothing is an answer, taken at once', async () => {
        const host = fakeHost({ listingOk: true });
        expect(await resolveDeepLink('api', host)).toBe(null);
        expect(methods(host).filter((m) => m === 'reloadRunningSessions')).toHaveLength(1);
    });

    test('a row appearing on a later attempt stops the ladder', async () => {
        const host = fakeHost({ listingOk: false });
        let ticks = 0;
        host.reloadRunningSessions = async () => {
            ticks += 1;
            if (ticks === 3) host.rows = [row({ name: 'cloude_api' })];
        };
        expect((await resolveDeepLink('api', host))?.name).toBe('cloude_api');
        expect(ticks).toBe(3);
    });
});

describe('deep-link resolution NEVER creates a session', () => {
    beforeEach(() => {
        expect(isResolvingDeepLink()).toBe(false);
    });

    test('a miss reaches Router.rejectTarget and creates nothing at all', async () => {
        const host = fakeHost({ listingOk: true });
        await openProjectByName('ghost', host, t);
        expect(methods(host)).toContain('rejectTarget');
        expect(methods(host)).not.toContain('createSession');
        expect(methods(host)).not.toContain('adoptSession');
    });

    test('THE MUTATION TARGET: the miss does not fall through to a project', async () => {
        const host = fakeHost({ listingOk: true });
        await openProjectByName('a-project-that-exists', host, t);
        expect(host.calls.filter((c) => c.method === 'createSession')).toEqual([]);
    });

    test('a LIVE row is entered, an idle one is NOT adopted (it is refused), and neither creates', async () => {
        const live = fakeHost({
            rows: [row({ name: 'cloude_api', is_active: true, session_id: 'ses_1' })],
        });
        await openProjectByName('api', live, t);
        expect(methods(live)).toContain('returnToExistingTerminal');
        expect(methods(live)).not.toContain('createSession');

        const idle = fakeHost({ rows: [row({ name: 'cloude_api', is_active: false })] });
        idle.adoptAnswer = { session: { working_dir: '/w', tmux_session: 'cloude_api' } };
        await openProjectByName('api', idle, t);
        expect(methods(idle)).not.toContain('adoptSession');
        expect(methods(idle)).not.toContain('createProject');
        expect(methods(idle)).not.toContain('createSession');
        expect(methods(idle)).not.toContain('announceSessionCreated');
        expect(idle.calls.filter((c) => c.method === 'rejectTarget')).toEqual([
            { method: 'rejectTarget', arg: 'api' },
        ]);
    });

    test('selectProject REFUSES while a resolution is in flight, loudly', async () => {
        const host = fakeHost({ listingOk: false });
        let refusal: unknown = null;
        host.reloadRunningSessions = async () => {
            try {
                await selectProject({ name: 'api', path: '/a' }, host, t);
            } catch (error) {
                refusal = error;
            }
            host.listingOk = true;
        };
        await openProjectByName('api', host, t);
        expect(refusal).toBeInstanceOf(Error);
        expect((refusal as Error).message).toContain('home.nav.deeplink_refuses_create');
        expect(methods(host)).not.toContain('createSession');
    });

    test('and the flag is cleared even when the resolution threw', async () => {
        const host = fakeHost({ listingOk: true });
        host.rejectTarget = () => {
            throw new Error('router exploded');
        };
        await expect(openProjectByName('x', host, t)).rejects.toThrow('router exploded');
        expect(isResolvingDeepLink()).toBe(false);
    });
});

describe('an adopt carries the row label across', () => {
    test('because the adopt response has none, and the tab title needs one', async () => {
        const host = fakeHost({ rows: [row({ name: 'cloude_x', label: 'Refactor spike' })] });
        host.adoptAnswer = { session: { working_dir: '/w' } };
        await attachRunningSession('cloude_x', host, t);
        const announced = host.calls.find((c) => c.method === 'announceSessionCreated');
        expect((announced?.arg as { session: SessionLike }).session.label).toBe('Refactor spike');
    });

    test('and NEVER overwrites a label the response did supply', async () => {
        const host = fakeHost({ rows: [row({ name: 'cloude_x', label: 'from the row' })] });
        host.adoptAnswer = { session: { working_dir: '/w', label: 'from the server' } };
        await attachRunningSession('cloude_x', host, t);
        const announced = host.calls.find((c) => c.method === 'announceSessionCreated');
        expect((announced?.arg as { session: SessionLike }).session.label).toBe('from the server');
    });

    test('the project row it writes is the BARE name, never cloude_-prefixed', async () => {
        const host = fakeHost({});
        host.adoptAnswer = { session: { working_dir: '/w', tmux_session: 'cloude_x' } };
        await attachRunningSession('cloude_x', host, t);
        const created = host.calls.find((c) => c.method === 'createProject');
        expect((created?.arg as { name: string }).name).toBe('x');
    });
});

describe('opening a project', () => {
    test('a cancelled provider pick creates nothing and reports nothing', async () => {
        const host = fakeHost({});
        let asked = 0;
        host.chooseProvider = async () => {
            asked += 1;
            return null;
        };
        await selectProject({ name: 'api', path: '/a' }, host, t);
        expect(asked).toBe(1);
        expect(methods(host)).toEqual([]);
    });

    test('the label travels as claude --name as well as the row title', async () => {
        const host = fakeHost({});
        await selectProject({ name: 'api', path: '/a' }, host, t);
        const payload = host.calls.find((c) => c.method === 'createSession')?.arg as Record<
            string,
            unknown
        >;
        expect(payload.label).toBe('api');
        expect(payload.project_name).toBe('api');
        expect(payload.working_dir).toBe('/a');
    });

    test('"already running" SWAPS: it detaches and retries, it does not refuse', async () => {
        const host = fakeHost({ createThrows: new Error('a session is already running') });
        let attempts = 0;
        host.createSession = async () => {
            attempts += 1;
            if (attempts === 1) throw new Error('a session is already running');
            return { id: 'ses_2' } as SessionLike;
        };
        await selectProject({ name: 'api', path: '/a' }, host, t, {});
        expect(methods(host)).toContain('detachSession');
        expect(attempts).toBe(2);
    });
});

describe('a layout wait may DELAY a rejoin, never cancel it', () => {
    test('so the rejoin still completes when frames never come', async () => {
        const host = fakeHost({});
        let entered = false;
        host.prepareTerminal = async () => ({ cols: 0, rows: 0 });
        host.returnToExistingTerminal = () => {
            entered = true;
        };
        await returnToActiveSession('ses_1', host, t);
        expect(entered).toBe(true);
        const asked = host.calls.find((c) => c.method === 'getSession');
        expect((asked?.arg as { options: { cols: number } }).options.cols).toBe(0);
    });
});

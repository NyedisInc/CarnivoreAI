import { afterEach, describe, expect, test } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { SessionHost } from './host';
import { sessionStore } from './store.svelte';
import type {
    AttachableSession,
    ProjectRow,
    SessionListItem,
    SessionRecord,
} from './types';

const en = createI18n({ locale: 'en' }) as { t(k: string, p?: unknown): string };
const t = (k: string, p?: Record<string, unknown> | null) => en.t(k, p);

const ENDPOINTS = [
    'attachable', 'authority', 'list', 'presence', 'projects', 'records',
] as const;

const settleMicrotasks = (): Promise<void> =>
    new Promise((resolve) => { setTimeout(resolve, 0); });

interface WaveRig {
    host: SessionHost;
    calls: string[];
    drain(): Promise<number>;
}

function waveRig(over: Partial<Record<string, unknown>> = {}): WaveRig {
    const calls: string[] = [];
    let pending: Array<() => void> = [];
    const probe = <T>(name: string, fallback: T) => (): Promise<T> => {
        calls.push(name);
        const answer = (name in over ? over[name] : fallback) as T | Error;
        return new Promise<T>((resolve, reject) => {
            pending.push(() => {
                if (answer instanceof Error) reject(answer);
                else resolve(answer);
            });
        });
    };
    const host: SessionHost = {
        getProjects: probe('projects', [] as ProjectRow[]),
        getProjectsPresence: probe('presence', { status: 'ok', projects: [] }),
        getProjectsAuthority: probe('authority', null as never),
        listAttachableSessions: probe('attachable', [{
            name: 'cloude_a', created_by_cloude: true, created_at_epoch: 5000,
            window_count: 1, status: 'idle',
        }] as AttachableSession[]),
        listSessions: probe('list', [{
            tmux_session: 'cloude_a', activity_status: 'working', unread: false,
            session: { id: 'ses_1' },
        }] as SessionListItem[]),
        getCurrentSession: probe('current', null),
        listSessionRecords: probe('records', [] as SessionRecord[]),
    };
    return {
        host,
        calls,
        async drain(): Promise<number> {
            let waves = 0;
            await settleMicrotasks();
            while (pending.length) {
                waves += 1;
                const batch = pending;
                pending = [];
                for (const release of batch) release();
                await settleMicrotasks();
            }
            return waves;
        },
    };
}

afterEach(() => {
    sessionStore.reset();
    sessionStore.useHost(null);
});

describe('the first paint is one round trip deep', () => {
    test('all six requests go out together and settle in ONE wave', async () => {
        const rig = waveRig();
        sessionStore.useHost(rig.host);

        const running = sessionStore.loadRunningSessions(t);
        const projects = sessionStore.loadProjects(false, t);
        const waves = await rig.drain();
        await Promise.all([running, projects]);

        expect(waves).toBe(1);
        expect([...rig.calls].sort()).toEqual([...ENDPOINTS]);
    });

    test('and it really did load: rows, verdict and join all landed', async () => {
        const rig = waveRig();
        sessionStore.useHost(rig.host);
        const running = sessionStore.loadRunningSessions(t);
        const projects = sessionStore.loadProjects(false, t);
        await rig.drain();
        await Promise.all([running, projects]);

        expect(sessionStore.runningSessions).toHaveLength(1);
        expect(sessionStore.runningSessions[0]?.is_active).toBe(true);
        expect(sessionStore.runningSessionsListing.ok).toBe(true);
        expect(sessionStore.sessionAttributionListingOk).toBe(true);
        expect(sessionStore.projectsListingOk).toBe(true);
    });

    test('the back-compat fallback is still gated behind an empty list', async () => {
        const rig = waveRig();
        sessionStore.useHost(rig.host);
        const running = sessionStore.loadRunningSessions(t);
        await rig.drain();
        await running;
        expect(rig.calls).not.toContain('current');
    });

    test('an empty live list is an answer: no second wave, no current-session call (#1974)', async () => {
        const rig = waveRig({ list: [] });
        sessionStore.useHost(rig.host);
        const running = sessionStore.loadRunningSessions(t);
        const waves = await rig.drain();
        await running;
        expect(rig.calls).not.toContain('current');
        expect(waves).toBe(1);
    });
});

describe('THE NEGATIVE CONTROL: the counter can report more than one', () => {
    test('a deliberately serial caller measures six waves on the same rig', async () => {
        const rig = waveRig();
        const serial = (async () => {
            await rig.host.getProjects(false);
            await rig.host.getProjectsPresence();
            await rig.host.getProjectsAuthority();
            await rig.host.listAttachableSessions();
            await rig.host.listSessions!();
            await rig.host.listSessionRecords();
        })();
        const waves = await rig.drain();
        await serial;
        expect(waves).toBe(6);
    });

    test('THE BEFORE NUMBER: the shape this replaced measures five', async () => {
        const rig = waveRig();
        const serial = (async () => {
            await rig.host.getProjects(false);
            await Promise.all([
                rig.host.getProjectsPresence(),
                rig.host.getProjectsAuthority(),
            ]);
            await rig.host.listAttachableSessions();
            await rig.host.listSessions!();
            await rig.host.listSessionRecords();
        })();
        const waves = await rig.drain();
        await serial;
        expect(waves).toBe(5);
    });
});

describe('THE SOURCE RULE: the sequencer starts before it awaits', () => {
    test('loadHomeScreen kicks the merge ahead of the list', async () => {
        const fs = await import('node:fs');
        const path = await import('node:path');
        const url = await import('node:url');
        const here = path.dirname(url.fileURLToPath(import.meta.url));
        const src = fs.readFileSync(path.join(here, '..', '..', 'main.ts'), 'utf8');
        const body = src.slice(src.indexOf('async function loadHomeScreen'));
        const fn = body.slice(0, body.indexOf('\n}'))
            .replace(/\/\*[\s\S]*?\*\//g, ' ')
            .replace(/^[ \t]*\/\/.*$/gm, ' ');

        const started = fn.indexOf('sessionStore.loadRunningSessions(t)');
        const awaited = fn.indexOf('await sessionStore.loadProjects');
        expect(started).toBeGreaterThan(-1);
        expect(awaited).toBeGreaterThan(-1);
        expect(started).toBeLessThan(awaited);
        expect(fn).not.toContain('void sessionStore.loadRunningSessions(t);');
    });
});

describe('concurrency did not collapse the two session verdicts', () => {
    test('a failed attachable probe still lets the live merge answer', async () => {
        const rig = waveRig({ attachable: new Error('HTTP 503') });
        sessionStore.useHost(rig.host);
        const running = sessionStore.loadRunningSessions(t);
        await rig.drain();
        await running;

        expect(sessionStore.runningSessionsListing.ok).toBe(false);
        expect(sessionStore.runningSessionsListing.sources).toEqual(['attachable']);
        expect(sessionStore.runningSessions.map((r) => r.name)).toEqual(['cloude_a']);
    });

    test('a failed live probe does not reach for the fallback', async () => {
        const rig = waveRig({ list: new Error('HTTP 500') });
        sessionStore.useHost(rig.host);
        const running = sessionStore.loadRunningSessions(t);
        await rig.drain();
        await running;

        expect(rig.calls).not.toContain('current');
        expect(sessionStore.runningSessionsListing.ok).toBe(false);
        expect(sessionStore.runningSessionsListing.sources).toEqual(['live']);
    });

    test('both failing names both sources, attachable first', async () => {
        const rig = waveRig({
            attachable: new Error('HTTP 503'), list: new Error('HTTP 500'),
        });
        sessionStore.useHost(rig.host);
        const running = sessionStore.loadRunningSessions(t);
        await rig.drain();
        await running;
        expect(sessionStore.runningSessionsListing.sources).toEqual(['attachable', 'live']);
    });
});

describe('the project sidecars are joined, not merely started', () => {
    test('presence and authority have landed before loadProjects resolves', async () => {
        const rig = waveRig({
            presence: { status: 'ok', projects: [{ raw_path: '/p', root: '/p' }] },
            authority: { mode: 'db', degraded: false },
        });
        sessionStore.useHost(rig.host);
        const projects = sessionStore.loadProjects(false, t);
        await rig.drain();
        await projects;
        expect(sessionStore.projectAuthority).toEqual({ mode: 'db', degraded: false });
        expect(sessionStore.projectPresence.get('/p')).toBeTruthy();
    });

    test('a failed project list still resolves, and still joins them', async () => {
        const rig = waveRig({
            projects: new Error('HTTP 500'),
            authority: { mode: 'db', degraded: false },
        });
        sessionStore.useHost(rig.host);
        const projects = sessionStore.loadProjects(true, t);
        await rig.drain();
        const result = await projects;

        expect(result.ok).toBe(false);
        expect(sessionStore.projectsListingOk).toBe(false);
        expect(sessionStore.archivedFetchOk).toBe(false);
        expect(sessionStore.projectAuthority).toEqual({ mode: 'db', degraded: false });
    });
});

/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { selectProject } from '../launchpad/navigation';
import { autoDelegateApi } from '../pack-transport/auto-delegate-api';
import { sessionPlaceApi } from '../session-place/api';
import { buildOpenProjectPayload } from '../launchpad/open-project-payload';
import { openModal } from '../modal';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import LaunchPickerModal from './LaunchPickerModal.svelte';
import type { LaunchProfilesApi, ProfileRow } from '../launch-profiles-page/api';
import { clean, readPlacement, refusalReason, startedLine, type PlacementBlock, type SessionPlaceApi } from '../session-place/api';

const i18n = createI18n({ locale: 'en' }) as { t(k: string, p?: Record<string, unknown> | null): string };
const t = (k: string, p?: Record<string, unknown> | null): string => i18n.t(k, p);

function row(id: string, harness: string): ProfileRow {
    return {
        id, harness, label: id, icon: null, description: null, default: true,
        account: { mode: 'follow_active', account_id: null }, endpoint: { mode: 'native', connection_id: null },
        model: { mode: 'default', value: null }, permissions: 'harness_default', flags: [], env: [], secrets: [],
        shell_profile: true, before_launch: null, custom_command: null, custom_command_ack_no_args: false,
        summary: { permissions_badge: 'default permissions', model: 'default', account: 'follow_active', endpoint: 'native' },
    } as ProfileRow;
}
const profiles = { list: async () => ({ revision: 1, profiles: [row('claude-main', 'claude'), row('codex-yolo', 'codex')] }), accounts: async () => [], models: async () => [], launchAccounts: async () => null } as unknown as LaunchProfilesApi;

async function settle(): Promise<void> { for (let i = 0; i < 12; i += 1) await Promise.resolve(); }
const q = <E extends HTMLElement>(sel: string): E => document.querySelector(sel) as E;
afterEach(() => { document.body.innerHTML = ''; });

function planner(block: PlacementBlock | Error): { api: SessionPlaceApi; asked: unknown[] } {
    const asked: unknown[] = [];
    return { asked, api: { explain: async (question) => { asked.push(question); if (block instanceof Error) throw block; return block; }, start: async () => { throw new Error('the picker never starts'); } } };
}
async function open(extra: Record<string, unknown>): Promise<{ answer: Promise<Record<string, unknown> | null> }> {
    const answer = openModal<Record<string, unknown> | null, Record<string, unknown>>(LaunchPickerModal as never, { title: 'x', t, api: profiles, ...extra });
    await settle();
    return { answer };
}
async function pickAuto(): Promise<void> { q('[data-lpm-computer="auto"]').click(); await settle(); }

describe('the computer row', () => {
    test('absent without placement (an unmarked project, a copy, a new project)', async () => {
        await open({});
        expect(q('[data-lpm-computer]')).toBeNull();
    });

    test('this computer is the default and answers here, with no read of the pack shown', async () => {
        const { api } = planner({ decision: 'here', computer: null, label: null, reason: 'x', code: null });
        const { answer } = await open({ placement: { workingDir: '/w', api } });
        expect(q('[data-lpm-computer="here"]').getAttribute('aria-checked')).toBe('true');
        expect(q('[data-lpm-computer-note]')).toBeNull();
        q('[data-lpm-go]').click();
        expect(await answer).toMatchObject({ computer: 'here' });
    });

    test.each([
        [{ decision: 'here', computer: null, label: null, reason: 'it is not busy', code: null }, 'auto: this computer, it is not busy'],
        [{ decision: 'remote', computer: 'i1', label: 'tower', reason: 'this computer is pegged', code: null }, 'auto: tower, this computer is pegged'],
        [{ decision: 'refused', computer: null, label: null, reason: 'nobody has swift', code: 'requirement_unmet' }, 'auto cannot start it: nobody has swift'],
    ] as [PlacementBlock, string][])('auto shows one preview line for %#', async (block, line) => {
        const { api, asked } = planner(block);
        const { answer } = await open({ placement: { workingDir: '/w', api } });
        expect(asked).toEqual([{ working_dir: '/w', agent_type: 'claude-main' }]);
        await pickAuto();
        expect(q('[data-lpm-computer-note]').textContent).toBe(line);
        q('[data-lpm-go]').click();
        expect(await answer).toMatchObject({ computer: 'auto', profileId: 'claude-main' });
    });

    test('an unreadable pack says this computer is used, and the preview text is never markup', async () => {
        await open({ placement: { workingDir: '/w', api: planner(new Error('down')).api } });
        await pickAuto();
        expect(q('[data-lpm-computer-note]').textContent).toBe('the pack could not be read; this computer is used');
        document.body.innerHTML = '';
        const evil = planner({ decision: 'remote', computer: 'i1', label: '<img src=x>', reason: '<b>hi</b>', code: null });
        await open({ placement: { workingDir: '/w', api: evil.api } });
        await pickAuto();
        expect(q('[data-lpm-computer-note]').textContent).toBe('auto: <img src=x>, <b>hi</b>');
        expect(q('[data-lpm-computer-note]').querySelector('img, b')).toBeNull();
    });
});

describe('the words of a placed start', () => {
    const remote: PlacementBlock = { decision: 'remote', computer: 'i1', label: 'tower', reason: 'this computer is pegged', code: null, left_behind: 2 };
    test('a remote start says where, what stayed home and where the work lives', () => {
        expect(startedLine(remote, t)).toBe("started on tower: this computer is pegged; 2 uncommitted files on this computer did not go; tower keeps this session's work until it pushes or you move it back");
    });
    test('a start here says only where', () => {
        expect(startedLine({ ...remote, decision: 'here', label: null, reason: 'it is not busy' }, t)).toBe('started on this computer: it is not busy');
    });
    test('strings from the other computer lose control bytes and are capped; a refusal reason is read off a 409', () => {
        expect(clean('a\u0007b\nc')).toBe('abc');
        expect(clean('x'.repeat(500))).toHaveLength(160);
        expect(readPlacement({ decision: 'nonsense', reason: 'r\u0000' }).decision).toBe('refused');
        expect(refusalReason({ payload: { detail: { placement: { reason: 'nobody has swift' } } } })).toBe('nobody has swift');
        expect(refusalReason(new Error('x'))).toBe('');
    });
});

describe('selectProject with the computer row', () => {
    const project = { name: 'api', path: '/w/api' } as never;
    function host(choice: Record<string, unknown>, offered: unknown[]): { host: never; created: unknown[]; announced: unknown[] } {
        const created: unknown[] = []; const announced: unknown[] = [];
        const h = {
            runningSessions: () => [], terminalDims: () => ({}),
            chooseProvider: async (_d: unknown, _a: unknown, _p: unknown, _f: unknown, placement: unknown) => { offered.push(placement); return choice; },
            createSession: async (payload: unknown) => { created.push(payload); return { tmux_session: 'a' }; },
            announceSessionCreated: (x: unknown) => { announced.push(x); },
        };
        return { host: h as never, created, announced };
    }
    afterEach(() => { vi.restoreAllMocks(); });

    test('an unmarked project is offered no row; a marked home project is', async () => {
        const offered: unknown[] = [];
        vi.spyOn(autoDelegateApi, 'get').mockResolvedValueOnce({ role: 'home', auto_delegate: false }).mockResolvedValueOnce({ role: 'copy' }).mockResolvedValueOnce({ role: 'home', auto_delegate: true });
        for (let i = 0; i < 3; i += 1) await selectProject(project, host({ wrapperId: 'claude-main' }, offered).host, t);
        expect(offered).toEqual([null, null, { workingDir: '/w/api' }]);
    });

    test('auto posts the open-project body to the placing route, this computer posts as before', async () => {
        vi.spyOn(autoDelegateApi, 'get').mockResolvedValue({ role: 'home', auto_delegate: true });
        const start = vi.spyOn(sessionPlaceApi, 'start').mockResolvedValue({ session: { tmux_session: 'remote' }, placement: { decision: 'remote', computer: 'i1', label: 'tower', reason: 'busy', code: null } });
        const auto = host({ wrapperId: 'claude-main', computer: 'auto' }, []);
        await selectProject(project, auto.host, t);
        const { request_id, ...body } = start.mock.calls[0]![0] as Record<string, unknown>;
        expect(request_id).toMatch(/^[0-9a-f]{32}$/);
        expect(body).toEqual(buildOpenProjectPayload('api', '/w/api', { wrapperId: 'claude-main', computer: 'auto' }, {}));
        expect(auto.created).toEqual([]);
        const here = host({ wrapperId: 'claude-main', computer: 'here' }, []);
        await selectProject(project, here.host, t);
        expect(start).toHaveBeenCalledTimes(1);
        expect(here.created).toHaveLength(1);
    });

    test('a 409 creates nothing and shows the refusal reason', async () => {
        vi.spyOn(autoDelegateApi, 'get').mockResolvedValue({ role: 'home', auto_delegate: true });
        vi.spyOn(sessionPlaceApi, 'start').mockRejectedValue(Object.assign(new Error('x'), { payload: { detail: { placement: { reason: 'nobody has swift' } } } }));
        const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
        const h = host({ wrapperId: 'claude-main', computer: 'auto' }, []);
        await selectProject(project, h.host, t);
        expect(h.created).toEqual([]);
        expect(h.announced).toEqual([]);
        expect(spy.mock.calls.some((c) => String(c[1]).includes('auto cannot start it: nobody has swift'))).toBe(true);
    });
});

/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as GroupStore from '../drawer/group-store';
import { createGroupThenAssign } from './group-assign';
import { judgeGroupName } from './group-name';

const modalAnswer = vi.hoisted(() => ({ current: null as { name: string; parentKey: string | null } | null }));
vi.mock('../modal', () => ({ openModal: vi.fn(async () => modalAnswer.current) }));

type Win = Record<string, unknown> & {
    API?: Record<string, (...args: never[]) => Promise<unknown>>;
    TextPromptModal?: { open: () => Promise<string | null> };
    SessionSidebar?: unknown;
    WriteFailureNotice?: unknown;
};
const win = globalThis as unknown as Win;

const group = (uuid: string, name: string) => ({
    group_uuid: uuid, name, position: 0, members: [], member_session_uuids: [], colour: null, gradient: null, animation: 'none', icon: null,
});
const existing = () => [group('g1', 'research')];

let calls: Array<[string, ...unknown[]]>;
let reports: string[];

beforeEach(() => {
    calls = [];
    reports = [];
    document.body.innerHTML = '<div id="session-sidebar-live"></div>';
    GroupStore.apply({ status: 'ok', groups: existing() });
    win.SessionSidebar = { repaint: () => {} };
    win.WriteFailureNotice = { report: (text: string) => reports.push(text) };
    win.API = {
        createSessionGroup: async (name: string) => { calls.push(['create', name]); return { status: 'ok', groups: [...existing(), group('g2', name)] }; },
        assignSessionGroup: async (name: string, uuid: string | null) => { calls.push(['assign', name, uuid]); return { status: 'ok', groups: [...existing(), group('g2', 'infra')] }; },
        listSessionGroups: async () => ({ status: 'ok', groups: existing() }),
    };
});

afterEach(() => {
    GroupStore.reset();
    delete win.SessionSidebar;
    delete win.WriteFailureNotice;
    delete win.API;
    delete win.TextPromptModal;
    document.body.replaceChildren();
});

function answers(answer: string | null, parentKey: string | null = null): void {
    modalAnswer.current = answer === null ? null : { name: answer, parentKey };
}

describe('judgeGroupName', () => {
    it('squeezes whitespace and keeps a usable name', () => {
        expect(judgeGroupName('  new   crew ', ['research'])).toEqual({ ok: true, value: 'new crew' });
    });

    it('refuses an empty or blank name', () => {
        expect(judgeGroupName('', [])).toEqual({ ok: false, reason: 'empty' });
        expect(judgeGroupName('  \t ', [])).toEqual({ ok: false, reason: 'empty' });
    });

    it('refuses a name that matches an existing group ignoring case and spacing', () => {
        expect(judgeGroupName(' Research ', ['research'])).toEqual({ ok: false, reason: 'duplicate' });
    });
});

describe('createGroupThenAssign', () => {
    it('cancel creates and files nothing', async () => {
        answers(null);
        await createGroupThenAssign('cloude_a');
        expect(calls).toEqual([]);
    });

    it('a name creates the group and files the session into it', async () => {
        answers('infra');
        await createGroupThenAssign('cloude_a');
        expect(calls).toEqual([['create', 'infra'], ['assign', 'cloude_a', 'g2']]);
    });

    it('an empty name is refused in words and sends nothing', async () => {
        answers('   ');
        await createGroupThenAssign('cloude_a');
        expect(calls).toEqual([]);
        expect(reports).toEqual(['a group needs a name, so no group was created']);
    });

    it('a duplicate name is refused in words and sends nothing', async () => {
        answers('Research');
        await createGroupThenAssign('cloude_a');
        expect(calls).toEqual([]);
        expect(reports).toEqual(['a group with that name already exists, so no group was created']);
    });

    it('files into the group just made, not an older twin of the same name another device made', async () => {
        answers('infra');
        win.API!.createSessionGroup = async () => {
            calls.push(['create', 'infra']);
            return { status: 'ok', groups: [group('g0', 'infra'), ...existing(), group('g9', 'infra')] } as never;
        };
        await createGroupThenAssign('cloude_a');
        expect(calls[1]).toEqual(['assign', 'cloude_a', 'g9']);
    });

    it('a refused file-in is said in words and the created group stays', async () => {
        answers('infra');
        win.API!.assignSessionGroup = async () => { throw new Error('session_not_stored'); };
        await createGroupThenAssign('ghost');
        expect(calls).toEqual([['create', 'infra']]);
        expect(reports).toEqual(['could not move ghost: session_not_stored']);
    });

    it('says so when the new group is missing from the answer, instead of announcing a create that filed nothing', async () => {
        answers('infra');
        win.API!.createSessionGroup = async () => ({ status: 'ok', groups: existing() }) as never;
        await createGroupThenAssign('cloude_a');
        expect(calls.some((c) => c[0] === 'assign')).toBe(false);
        expect(reports).toEqual(["could not create the group: the new group was not in the server's answer, so nothing was filed"]);
    });
});

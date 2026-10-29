/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ClosedRows from './ClosedRows.svelte';
import PanelFacts from './PanelFacts.svelte';
import PanelHead from './PanelHead.svelte';
import { closedByKey, closedOnlyGroups, closedRowsFrom, closedShown, historyKeyOf, previewCount } from './closed-model';
import { NO_FILTERS, rowsFromGroups, type PageRow, type Signals } from './filters';
import { rowAction } from './row-action';
import { SessionsData, closedQuery } from './sessions-data.svelte';
import type { HistoryApi, HistoryPage } from '../projects-shared/history-api';
import { group, session } from '../projects-shared/test-fixtures';
import { t, setLocale } from '../i18n/index.svelte';

setLocale('en');

const sig: Signals = { live: () => undefined, asleepUnread: () => false };
const ON = { ...NO_FILTERS, on: ['working', 'sleep', 'closed'] } as const;
const labels = { noCompany: 'no company', thisComputer: 'this computer' };
const rowOf = (patch: Parameters<typeof session>[0], peer?: string): PageRow => {
    const g = group({ name: 'alpha', key: peer ? `peer-x:1` : '1', ...(peer ? { host_label: peer } : {}), sessions: [session({ agent_family: 'claude', ...patch })] });
    return rowsFromGroups(peer ? [] : [g], peer ? [g] : [], 'none')[0] as PageRow;
};

let handle: ReturnType<typeof mount> | null = null;
afterEach(() => {
    if (handle) void unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

describe('the closed read and the join', () => {
    test('asks for closed sessions, and for removed ones and automated runs only while show hidden is on', () => {
        const off = new URLSearchParams(closedQuery(0, false));
        const on = new URLSearchParams(closedQuery(0, true));
        expect(off.get('state')).toBe('closed,unknown');
        expect(on.get('state')).toBe('closed,removed,unknown');
        expect(off.get('include_automated')).toBe('false');
        expect(on.get('include_automated')).toBe('true');
    });

    test('the data layer keeps closed rows apart from the open rows and never lets an open session into them', async () => {
        const open = group({ name: 'alpha', key: '1', sessions: [session({ session_uuid: 'a', agent_family: 'claude', state: 'running' })] });
        const shut = group({ name: 'alpha', key: '1', sessions: [session({ session_uuid: 'b', agent_family: 'claude', state: 'closed' }), session({ session_uuid: 'leak', agent_family: 'claude', state: 'running' })] });
        const page = (g: typeof open): HistoryPage => ({ state: 'ok', total: 1, offset: 0, limit: 100, next_offset: null, groups: [g], facets: { agents: [], states: {} } });
        const list = vi.fn((q: string) => Promise.resolve(page(q.includes('closed') ? shut : open)));
        const data = new SessionsData({ list } as unknown as HistoryApi, { records: () => Promise.resolve([]), counts: () => Promise.resolve({}) }, 'none', 'no datastore');
        await data.refresh();
        expect(data.rows.map((r) => r.s.session_uuid)).toEqual(['a']);
        expect(data.closedRows.map((r) => r.s.session_uuid)).toEqual(['b']);
    });

    test('a closed row joins its project group by the history key, and a group with no project group gets a heading of its own', () => {
        const r = rowOf({ session_uuid: 'c1' });
        const g = { key: 'project:1', label: 'alpha', bits: [], measure: '', rows: [r], count: 1, live: 1, project: r.projectRef, provider: null };
        expect(historyKeyOf(g)).toBe('1');
        expect(historyKeyOf({ ...g, rows: [] })).toBe('1');
        const by = closedByKey([r, rowOf({ session_uuid: 'c2', last_activity_at: '2026-10-01T00:00:00Z' })]);
        expect(by.get('1')?.map((x) => x.s.session_uuid)).toEqual(['c2', 'c1']);
        expect(closedOnlyGroups(by, new Set(['1']))).toEqual([]);
        expect(closedOnlyGroups(by, new Set()).map((x) => [x.key, x.label, x.project])).toEqual([['closed:1', 'alpha', null]]);
        expect(closedRowsFrom([group({ name: 'a', key: '1', sessions: [session({ state: 'running', agent_family: 'claude' })] })], [], 'none')).toEqual([]);
    });

    test('a paired computer shows only once the computer filter is set, and only for that computer', () => {
        const mine = rowOf({ session_uuid: 'm' });
        const theirs = rowOf({ session_uuid: 'p', host_key: 'remote:peer-x' }, 'studio');
        expect(closedShown(mine, ON, labels)).toBe(true);
        expect(closedShown(theirs, ON, labels)).toBe(false);
        expect(closedShown(theirs, { ...ON, computer: 'studio' }, labels)).toBe(true);
        expect(closedShown(mine, { ...ON, computer: 'studio' }, labels)).toBe(false);
    });

    test('a long closed list is cut to six, a short overflow of two is not', () => {
        expect(previewCount(8, false)).toBe(8);
        expect(previewCount(9, false)).toBe(6);
        expect(previewCount(9, true)).toBe(9);
    });
});

describe('the one action a closed row leads with', () => {
    test('resume while the transcript is on disk, restart when it never had a conversation, nothing when it is gone or on a paired computer', () => {
        expect(rowAction(session({ state: 'closed', has_transcript: true, claude_session_uuid: 'x' }))).toBe('resume');
        expect(rowAction(session({ state: 'closed', has_transcript: false, claude_session_uuid: null }))).toBe('restart');
        expect(rowAction(session({ state: 'closed', has_transcript: false, claude_session_uuid: 'x' }))).toBeNull();
        expect(rowAction(session({ state: 'closed', has_transcript: true, claude_session_uuid: 'x', host_key: 'remote:peer-x' }))).toBeNull();
        expect(rowAction(session({ state: 'asleep', has_transcript: true, host_key: 'remote:peer-x' }))).toBeNull();
        expect(rowAction(session({ state: 'asleep', has_transcript: true }))).toBe('wake');
    });
});

describe('the closed lines', () => {
    function draw(rows: PageRow[], over: Record<string, unknown> = {}): { act: ReturnType<typeof vi.fn>; select: ReturnType<typeof vi.fn> } {
        const act = vi.fn();
        const select = vi.fn();
        handle = mount(ClosedRows, { target: document.body, props: { rows, selected: null, busyIds: new Set<string>(), searching: true, t, age: () => '3d', previousOf: (id: string) => (id === 'c1' ? 2 : 0), thisComputer: 'this computer', onSelect: select, onAct: act, ...over } });
        flushSync();
        return { act, select };
    }

    test('tags the transcript, counts earlier conversations and resumes with the one action', () => {
        const { act, select } = draw([rowOf({ session_uuid: 'c1', has_transcript: true, claude_session_uuid: 'x' })]);
        const line = document.querySelector<HTMLElement>('[data-closed-id="c1"]')!;
        expect(line.querySelector('[data-tag="on-disk"]')).not.toBeNull();
        expect(line.querySelector('[data-previous-count]')?.textContent).toBe('2 earlier');
        line.querySelector<HTMLButtonElement>('[data-go="resume"]')!.click();
        expect(act).toHaveBeenCalledWith('resume', expect.objectContaining({ s: expect.objectContaining({ session_uuid: 'c1' }) }));
        expect(select).not.toHaveBeenCalled();
        line.click();
        expect(select).toHaveBeenCalledTimes(1);
    });

    test('a gone transcript says so in coral and its resume is disabled with the reason', () => {
        draw([rowOf({ session_uuid: 'c2', has_transcript: false, claude_session_uuid: 'x' })]);
        const line = document.querySelector<HTMLElement>('[data-closed-id="c2"]')!;
        expect(line.querySelector('[data-tag="gone"]')).not.toBeNull();
        const b = line.querySelector<HTMLButtonElement>('[data-go="disabled"]')!;
        expect(b.disabled).toBe(true);
        expect(b.title).toBe('transcript gone and no conversation backup');
    });

    test('a paired computer row is history only: no button at all', () => {
        draw([rowOf({ session_uuid: 'p1', has_transcript: true, claude_session_uuid: 'x', host_key: 'remote:peer-x' }, 'studio')]);
        const line = document.querySelector<HTMLElement>('[data-closed-id="p1"]')!;
        expect(line.querySelector('button')).toBeNull();
        expect(line.textContent).toContain('studio');
    });

    test('the list is folded until opened, shows six and the rest on show all', () => {
        const many = Array.from({ length: 9 }, (_, i) => rowOf({ session_uuid: `s${i}` }));
        draw(many, { searching: false });
        expect(document.querySelectorAll('[data-closed-id]').length).toBe(0);
        document.querySelector<HTMLButtonElement>('[data-closed-head]')!.click();
        flushSync();
        expect(document.querySelectorAll('[data-closed-id]').length).toBe(6);
        document.querySelector<HTMLButtonElement>('[data-show-all]')!.click();
        flushSync();
        expect(document.querySelectorAll('[data-closed-id]').length).toBe(9);
    });
});

describe('the side panel extras', () => {
    function head(row: PageRow): { act: ReturnType<typeof vi.fn> } {
        const act = vi.fn();
        handle = mount(PanelHead, { target: document.body, props: { row, live: undefined, pinned: false, keptAwake: false, t, onAct: act, onPin: vi.fn() } });
        flushSync();
        return { act };
    }

    test('a removed session puts back, a closed one removes, the line says why resume is what it is', () => {
        const removed = head(rowOf({ state: 'removed', has_transcript: true, claude_session_uuid: 'x', tmux_name: null }));
        document.querySelector<HTMLButtonElement>('[data-pn-act="put-back"]')!.click();
        expect(removed.act).toHaveBeenCalledWith('put-back', expect.anything());
        expect(document.querySelector('[data-pn-act="remove"]')).toBeNull();
        expect(document.querySelector('[data-resume-why]')?.textContent).toBe('the transcript is still on disk, so resume continues the conversation from its last line.');
        unmount(handle!);
        document.body.innerHTML = '';
        const closed = head(rowOf({ state: 'closed', has_transcript: false, claude_session_uuid: 'x', tmux_name: null }));
        document.querySelector<HTMLButtonElement>('[data-pn-act="remove"]')!.click();
        expect(closed.act).toHaveBeenCalledWith('remove', expect.anything());
        expect(document.querySelector('[data-resume-why]')?.textContent).toBe('the transcript is gone from disk, so this cannot resume.');
    });

    test('a paired computer session gets no put back, remove, resume or why line', () => {
        head(rowOf({ state: 'closed', has_transcript: true, claude_session_uuid: 'x', host_key: 'remote:peer-x' }, 'studio'));
        expect(document.querySelector('[data-pn-act]')).toBeNull();
        expect(document.querySelector('[data-resume-why]')).toBeNull();
        expect(document.querySelector('[data-pic="pin"]')).toBeNull();
    });

    test('a paired computer running row shows no keep-awake control even when kept awake is passed', () => {
        const mount1 = (row: PageRow): void => {
            handle = mount(PanelHead, { target: document.body, props: { row, live: undefined, pinned: false, keptAwake: true, t, onAct: vi.fn(), onPin: vi.fn() } });
            flushSync();
        };
        mount1(rowOf({ state: 'running', host_key: 'remote:peer-x' }, 'studio'));
        expect(document.querySelector('.sp-pic-cup')).toBeNull();
        expect(document.querySelector('.kaw-icon')).toBeNull();
        unmount(handle!);
        document.body.innerHTML = '';
        mount1(rowOf({ state: 'running' }));
        expect(document.querySelector('.sp-pic-cup')).not.toBeNull();
    });

    test('the facts carry the transcript path, or gone with the reason', () => {
        const facts = (row: PageRow): string => {
            handle = mount(PanelFacts, { target: document.body, props: { row, worked: null, previous: 0, t, age: () => '1d' } });
            flushSync();
            const text = document.querySelector('[data-facts-transcript]')?.textContent ?? '';
            unmount(handle);
            handle = null;
            document.body.innerHTML = '';
            return text;
        };
        expect(facts(rowOf({ state: 'closed', has_transcript: true, claude_session_uuid: 'abc', working_dir: '/x/my dir' }))).toContain('~/.claude/projects/-x-my-dir/abc.jsonl');
        const gone = facts(rowOf({ state: 'closed', has_transcript: false, claude_session_uuid: 'abc' }));
        expect(gone).toContain('gone');
        expect(gone).toContain('claude code clears old transcripts after 30 days by default');
    });
});

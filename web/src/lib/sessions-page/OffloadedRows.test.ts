/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const promptRestore = vi.hoisted(() => vi.fn(async (_target: unknown, _followUp?: boolean) => true));
vi.mock('../offload-prompt/offload-prompt', async (original) => ({ ...(await original<object>()), promptRestore }));

import ClosedRows from './ClosedRows.svelte';
import PanelHead from './PanelHead.svelte';
import { closedShown } from './closed-model';
import { NO_FILTERS, rowsFromGroups, type PageRow } from './filters';
import { restoreOffloadedSession } from './restore-offloaded';
import { rowAction } from './row-action';
import { closedQuery } from './sessions-data.svelte';
import { group, session } from '../projects-shared/test-fixtures';
import { t, setLocale } from '../i18n/index.svelte';

setLocale('en');

const OFFLOADED = { state: 'removed', agent_family: 'claude', origin: 'imported', tmux_name: null, claude_session_uuid: 'c1', has_transcript: false, offloaded: true } as const;
const rowOf = (patch: Parameters<typeof session>[0]): PageRow =>
    rowsFromGroups([group({ name: 'alpha', key: '1', sessions: [session(patch)] })], [], 'none')[0] as PageRow;
const labels = { noCompany: 'no company', thisComputer: 'this computer' };

let handle: ReturnType<typeof mount> | null = null;
afterEach(() => {
    if (handle) void unmount(handle);
    handle = null;
    document.body.innerHTML = '';
    promptRestore.mockClear();
});

describe('reaching the row', () => {
    test('the closed read asks for offloaded rows, and a removed offloaded row shows under the closed toggle alone', () => {
        expect(new URLSearchParams(closedQuery(0, false)).get('offloaded')).toBe('true');
        const on = { ...NO_FILTERS, on: ['closed'] } as const;
        expect(closedShown(rowOf(OFFLOADED), on, labels)).toBe(true);
        expect(closedShown(rowOf({ ...OFFLOADED, offloaded: false }), on, labels)).toBe(false);
    });
});

describe('the closed row and the panel', () => {
    test('an offloaded closed row leads with restore, wears the offloaded tag, and a press restores through the one prompt', async () => {
        const row = rowOf({ ...OFFLOADED, state: 'closed' });
        expect(rowAction(row.s)).toBe('restore');
        const act = vi.fn();
        handle = mount(ClosedRows, { target: document.body, props: { rows: [row], selected: null, busyIds: new Set<string>(), searching: true, t, age: () => '3d', previousOf: () => 0, thisComputer: 'this computer', onSelect: vi.fn(), onAct: act } });
        flushSync();
        const line = document.querySelector<HTMLElement>('[data-closed-id]')!;
        expect(line.querySelector('[data-tag="offloaded"]')).not.toBeNull();
        line.querySelector<HTMLButtonElement>('[data-go="restore"]')!.click();
        expect(act).toHaveBeenCalledWith('restore', row);
        const done = vi.fn();
        await restoreOffloadedSession(row.s, done);
        expect(promptRestore).toHaveBeenCalledWith({ sessionUuid: row.s.session_uuid, label: row.s.label ?? row.s.title });
        expect(done).toHaveBeenCalledTimes(1);
    });

    test('a declined prompt re-reads nothing', async () => {
        promptRestore.mockResolvedValueOnce(false);
        const done = vi.fn();
        await restoreOffloadedSession(rowOf(OFFLOADED).s, done);
        expect(done).not.toHaveBeenCalled();
    });

    test('the panel head offers restore for an offloaded session, and put back stays for a removed one', () => {
        const act = vi.fn();
        handle = mount(PanelHead, { target: document.body, props: { row: rowOf(OFFLOADED), live: undefined, pinned: false, keptAwake: false, t, onAct: act, onPin: vi.fn() } });
        flushSync();
        document.querySelector<HTMLButtonElement>('[data-pn-act="restore"]')!.click();
        expect(act).toHaveBeenCalledWith('restore', expect.anything());
        expect(document.querySelector('[data-pn-act="put-back"]')).not.toBeNull();
    });
});

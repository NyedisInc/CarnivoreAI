/** @vitest-environment jsdom */
import { flushSync, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { setLocale } from '../../lib/i18n/index.svelte';
import { ApiError, type Translate } from '../sdk';
import OffloadedList from './OffloadedList.svelte';
import { OFFLOAD_TOPIC, type OffloadRow } from './offload-api';
import { dayText, factsText, nameText } from './offload-text';
import type { Fetcher } from './plugin-settings-api';

setLocale('en');

const DAY = Date.parse('2026-10-24T12:00:00Z') / 1000;
const row = (over: Partial<OffloadRow> = {}): OffloadRow => ({
    kind: 'session', session_uuid: 'S1-aaaa-bbbb', conversation_id: null, title: 'build the thing', project_id: 3, project: 'carnivore',
    conversations: 3, bytes: 3 * 1024 * 1024, offloaded_at: DAY, state: 'offloaded', error: '', ...over,
});
const LOOSE = row({ kind: 'conversation', session_uuid: null, conversation_id: 'cccccccc-1111', title: null, project: null, project_id: null, conversations: 1 });

interface Call { path: string; method: string; body: Record<string, unknown> | null }

function harness(pages: OffloadRow[][], opts: { enabled?: boolean; restore?: unknown; settings?: Record<string, unknown>; batch?: Record<string, unknown> | null; restoreBatch?: Record<string, unknown> | null } = {}) {
    const calls: Call[] = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        const call = { path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null };
        calls.push(call);
        if (path === '/cplugs/save') return call.method === 'PUT' ? {} : { revision: 4, settings: opts.settings ?? { vaultLocation: 'x' } };
        if (call.method === 'POST' && path.endsWith('/offload/restore-batch')) return { id: 'r1', state: 'running', planned: 2, restored: 0, failed: 0, bytes: 0 };
        if (call.method === 'POST') {
            if (opts.restore instanceof ApiError) throw opts.restore;
            return opts.restore ?? { conversations: [{ conversation_id: 'c1', status: 'written' }] };
        }
        const cursor = new URL(path, 'http://x').searchParams.get('cursor');
        const index = cursor ? Number(cursor) : 0;
        const rows = pages[index] ?? [];
        return { enabled: opts.enabled ?? false, batch: opts.batch ?? null, restore_batch: opts.restoreBatch ?? null, totals: { rows: pages.flat().length, conversations: 4, bytes: 4 * 1024 * 1024 }, rows, next_cursor: index + 1 < pages.length ? String(index + 1) : null };
    }) as unknown as Fetcher;
    return { fetcher, calls };
}

function pushStore() {
    let refresh: (() => void) | null = null;
    const stop = vi.fn();
    const store = { pushOrPoll: vi.fn((fn: () => void, _ms: number, topics: readonly string[]) => { refresh = fn; expect(topics).toEqual([OFFLOAD_TOPIC]); return stop; }) };
    return { store, fire: () => refresh?.(), stop };
}

async function settle(): Promise<void> {
    for (let i = 0; i < 8; i += 1) await tick();
    flushSync();
}

let target: HTMLElement;
let panel: Record<string, unknown> | null = null;
afterEach(() => {
    if (panel) unmount(panel);
    panel = null;
    target?.remove();
});

async function render(fetcher: Fetcher, push = pushStore().store): Promise<HTMLElement> {
    target = document.createElement('div');
    document.body.appendChild(target);
    panel = mount(OffloadedList, { target, props: { fetcher, push } });
    await settle();
    return target;
}
const q = (el: ParentNode, sel: string) => el.querySelector<HTMLElement>(`[data-tm="${sel}"]`);

describe('the offloaded list', () => {
    test('one row per session with name, project, count, size, day, state and a restore button always shown', async () => {
        const el = await render(harness([[row()]]).fetcher);
        const rows = el.querySelectorAll('[data-tm="offload-row"]');
        expect(rows).toHaveLength(1);
        expect(q(rows[0]!, 'offload-name')!.textContent).toBe('build the thing');
        expect(q(rows[0]!, 'offload-facts')!.textContent).toBe(`carnivore, 3 conversations, 3.0 mb, offloaded ${dayText(DAY)}`);
        expect(q(rows[0]!, 'offload-state')!.textContent).toBe('offloaded');
        expect(q(rows[0]!, 'offload-restore')!.textContent?.trim()).toBe('restore');
        expect(el.querySelector('[aria-haspopup]')).toBeNull();
    });

    test('a row stuck on a copy elsewhere says so from the catalog and names the path', async () => {
        const stuck = row({ state: 'conflict', error: 'this conversation is already on disk at /p/-x/c1.jsonl', error_code: 'present_elsewhere', error_path: '/p/-x/c1.jsonl' });
        const el = await render(harness([[stuck]]).fetcher);
        const why = q(el.querySelector('[data-tm="offload-row"]')!, 'offload-why')!.textContent!;
        expect(why).toBe('a copy is already on disk at /p/-x/c1.jsonl, outside the folder the session resumes from. nothing was written or moved.');
    });

    test('a conflict or failed row says why, and conversations no session holds sit under their own heading', async () => {
        const el = await render(harness([[row({ state: 'failed', error: '2 file(s) could not be put back: x' }), LOOSE]]).fetcher);
        const rows = [...el.querySelectorAll('[data-tm="offload-row"]')];
        expect(q(rows[0]!, 'offload-why')!.textContent).toBe('2 file(s) could not be put back: x');
        expect(q(rows[1]!, 'offload-why')).toBeNull();
        expect(q(rows[1]!, 'offload-name')!.textContent).toBe('conversation cccccccc');
        const heading = q(el, 'offload-loose-heading')!;
        expect(heading.textContent).toBe('no session');
        expect(heading.compareDocumentPosition(rows[1]!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(heading.compareDocumentPosition(rows[0]!) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
    });

    test('restore calls the session route once, names the result and reads the list again', async () => {
        const { fetcher, calls } = harness([[row()]]);
        const el = await render(fetcher);
        q(el, 'offload-restore')!.click();
        await settle();
        const posts = calls.filter((c) => c.method === 'POST');
        expect(posts.map((c) => c.path)).toEqual(['/cplugs/save/offload/sessions/S1-aaaa-bbbb/restore']);
        expect(q(el, 'offload-note')!.textContent).toBe('build the thing: 1 of 1 conversations are back in the projects folder');
        expect(calls.filter((c) => c.path.startsWith('/cplugs/save/offload?')).length).toBe(2);
    });

    test('a conversation with no session restores through the conversation route; a refusal is shown, not swallowed', async () => {
        const refusal = new ApiError('HTTP 409', 409, 'vault_unavailable', { detail: { code: 'vault_unavailable', detail: 'the vault is not reachable' } });
        const { fetcher, calls } = harness([[LOOSE]], { restore: refusal });
        const el = await render(fetcher);
        q(el, 'offload-restore')!.click();
        await settle();
        expect(calls.find((c) => c.method === 'POST')!.path).toBe('/cplugs/save/offload/conversations/cccccccc-1111/restore');
        expect(q(el, 'offload-problem')!.textContent).toContain('the vault is not reachable');
    });

    test('pages at the server cursor and shows more on request', async () => {
        const second = row({ session_uuid: 'S2', title: 'second' });
        const { fetcher } = harness([[row()], [second]]);
        const el = await render(fetcher);
        expect(el.querySelectorAll('[data-tm="offload-row"]')).toHaveLength(1);
        q(el, 'offload-more')!.click();
        await settle();
        expect(el.querySelectorAll('[data-tm="offload-row"]')).toHaveLength(2);
        expect(q(el, 'offload-more')).toBeNull();
    });

    test('says so when nothing is offloaded', async () => {
        const el = await render(harness([[]]).fetcher);
        expect(q(el, 'offload-empty')!.textContent).toBe('nothing is offloaded.');
        expect(q(el, 'offload-restore')).toBeNull();
    });
});

describe('the offload switch', () => {
    test('is off by default and says what off means; the list and restore still show', async () => {
        const el = await render(harness([[row()]]).fetcher);
        expect(q(el, 'offload-switch')!.getAttribute('aria-checked')).toBe('false');
        expect(q(el, 'offload-switch-hint')!.textContent).toContain('switched off');
        expect(q(el, 'offload-restore')).not.toBeNull();
    });

    test('flipping it writes only offloadEnabled with the revision, and keeps the other settings out of the write', async () => {
        const { fetcher, calls } = harness([[row()]]);
        const el = await render(fetcher);
        q(el, 'offload-switch')!.click();
        await settle();
        expect(calls.find((c) => c.method === 'PUT')).toEqual({ path: '/cplugs/save', method: 'PUT', body: { revision: 4, settings: { offloadEnabled: true } } });
    });

    test('shows on when the server says so', async () => {
        const el = await render(harness([[row()]], { enabled: true }).fetcher);
        expect(q(el, 'offload-switch')!.getAttribute('aria-checked')).toBe('true');
        expect(q(el, 'offload-switch-hint')!.textContent).toContain('on:');
    });
});

describe('the switch when the list cannot be read', () => {
    function listDown(settings: Record<string, unknown> | null): Fetcher {
        return (async (path: string, init?: RequestInit) => {
            if (path === '/cplugs/save' && (init?.method ?? 'GET') === 'GET') {
                if (settings === null) throw new ApiError('HTTP 503', 503, 'state_unreadable', {});
                return { revision: 4, settings };
            }
            throw new ApiError('HTTP 409', 409, 'vault_unavailable', { detail: { code: 'vault_unavailable', detail: 'the vault is not reachable' } });
        }) as unknown as Fetcher;
    }

    test('reads the stored setting instead of drawing off: an on switch must never look off while the vault is away', async () => {
        const el = await render(listDown({ offloadEnabled: true }));
        expect(q(el, 'offload-problem')!.textContent).toContain('the vault is not reachable');
        expect(q(el, 'offload-switch')!.getAttribute('aria-checked')).toBe('true');
        expect(q(el, 'offload-switch')!.hasAttribute('disabled')).toBe(false);
    });

    test('with neither read answering, the switch is not offered at all rather than guessed', async () => {
        const el = await render(listDown(null));
        expect(q(el, 'offload-switch')!.hasAttribute('disabled')).toBe(true);
    });
});

describe('paging while the ledger moves', () => {
    test('a row that slid onto the next page (a newer offload landed in between) is not drawn twice', async () => {
        const second = row({ session_uuid: 'S2', title: 'second' });
        const third = row({ session_uuid: 'S3', title: 'third' });
        const el = await render(harness([[row(), second], [second, third]]).fetcher);
        q(el, 'offload-more')!.click();
        await settle();
        expect([...el.querySelectorAll('[data-tm="offload-row"]')].map((r) => r.getAttribute('data-key'))).toEqual(['S1-aaaa-bbbb', 'S2', 'S3']);
    });
});

describe('the push', () => {
    test('reads on the topic, arms the push for exactly that topic, and stops it when the panel goes', async () => {
        const { fetcher, calls } = harness([[row()]]);
        const push = pushStore();
        await render(fetcher, push.store);
        const reads = () => calls.filter((c) => c.path.startsWith('/cplugs/save/offload?')).length;
        expect(reads()).toBe(1);
        push.fire();
        await settle();
        expect(reads()).toBe(2);
        unmount(panel!);
        panel = null;
        expect(push.stop).toHaveBeenCalledTimes(1);
    });
});

describe('the words', () => {
    test('a row with no title is named by its short id, and one conversation reads as singular', () => {
        const t: Translate = (key, p) => `${key}:${JSON.stringify(p ?? {})}`;
        expect(nameText(row({ title: '  ' }), t)).toContain('"id":"S1-aaaa-"');
        expect(factsText(row({ conversations: 1, project: null }), t)).toContain('count_one');
    });
});

describe('the staged bulk offload (slice 6)', () => {
    const batch = (over: Record<string, unknown> = {}) => ({ id: 'b1', state: 'running', planned: 10, offloaded: 4, skipped: 1, failed: 0, bytes: 1024, ...over });

    test('a running batch shows its progress and a stop button that asks the server to stop it', async () => {
        const { fetcher, calls } = harness([[row()]], { enabled: true, batch: batch() });
        const el = await render(fetcher);
        expect(q(el, 'offload-batch')?.dataset.state).toBe('running');
        expect(q(el, 'offload-batch-progress')?.textContent).toContain('4 of 10 sessions offloaded, 1 skipped, 0 failed');
        q(el, 'offload-batch-stop')!.click();
        await settle();
        expect(calls.find((c) => c.method === 'POST')).toMatchObject({ path: '/cplugs/save/offload/batch/b1/stop' });
    });

    test('a finished batch keeps its summary and has no stop button; no batch draws nothing', async () => {
        const done = await render(harness([[row()]], { batch: batch({ state: 'failed', offloaded: 2 }) }).fetcher);
        expect(q(done, 'offload-batch-progress')?.textContent).toContain('stopped at a failure');
        expect(q(done, 'offload-batch-stop')).toBeNull();
        unmount(panel!);
        panel = null;
        target.remove();
        expect(q(await render(harness([[row()]]).fetcher), 'offload-batch')).toBeNull();
    });
});

describe('the bulk restore (#2868)', () => {
    const A = row({ session_uuid: 'S1', title: 'first' });
    const B = row({ session_uuid: 'S2', title: 'second' });
    const restoreBatch = (over: Record<string, unknown> = {}) => ({ id: 'r1', state: 'running', planned: 5, restored: 3, failed: 1, bytes: 1024, items: [], ...over });
    const picks = (el: HTMLElement) => [...el.querySelectorAll<HTMLInputElement>('[data-tm="offload-pick"]')];
    const click = async (box: Element | null) => { (box as HTMLInputElement).click(); await settle(); };

    test('every row has a check box, "restore selected" is off until one is picked, and the count follows the picks', async () => {
        const el = await render(harness([[A, B, LOOSE]]).fetcher);
        expect(picks(el)).toHaveLength(3);
        const button = q(el, 'offload-restore-selected') as HTMLButtonElement;
        expect(button.disabled).toBe(true);
        await click(picks(el)[0]!);
        expect(button.disabled).toBe(false);
        expect(q(el, 'offload-picked')!.textContent).toBe('1 picked');
    });

    test('select all picks every row shown, and again clears them', async () => {
        const el = await render(harness([[A, B]]).fetcher);
        await click(el.querySelector('[data-tm="offload-select-all"]'));
        expect(picks(el).every((box) => box.checked)).toBe(true);
        expect(q(el, 'offload-picked')!.textContent).toBe('2 picked');
        await click(el.querySelector('[data-tm="offload-select-all"]'));
        expect(picks(el).some((box) => box.checked)).toBe(false);
    });

    test('restore selected sends ONE batch naming the picked sessions and conversations, never a call per row', async () => {
        const { fetcher, calls } = harness([[A, B, LOOSE]]);
        const el = await render(fetcher);
        await click(picks(el)[0]!);
        await click(picks(el)[2]!);
        await click(q(el, 'offload-restore-selected'));
        const posts = calls.filter((c) => c.method === 'POST');
        expect(posts).toHaveLength(1);
        expect(posts[0]).toMatchObject({ path: '/cplugs/save/offload/restore-batch', body: { session_uuids: ['S1'], conversation_ids: ['cccccccc-1111'] } });
        expect(q(el, 'offload-picked')!.textContent).toBe('0 picked');
    });

    test('the progress line reads "{done} of {planned} restored, {failed} failed" and a stop button shows only while it runs', async () => {
        const { fetcher, calls } = harness([[A]], { restoreBatch: restoreBatch() });
        const el = await render(fetcher);
        expect(q(el, 'restore-batch-progress')!.textContent).toContain('3 of 5 restored, 1 failed');
        await click(q(el, 'restore-batch-stop'));
        expect(calls.find((c) => c.method === 'POST')).toMatchObject({ path: '/cplugs/save/offload/restore-batch/r1/stop' });
        unmount(panel!);
        panel = null;
        target.remove();
        const done = await render(harness([[A]], { restoreBatch: restoreBatch({ state: 'done' }) }).fetcher);
        expect(q(done, 'restore-batch-stop')).toBeNull();
        expect(q(done, 'restore-batch-progress')!.textContent).toContain('finished');
    });

    test('while a bulk restore runs the check boxes and the button are off; nothing can be picked', async () => {
        const running = await render(harness([[A, B]], { restoreBatch: restoreBatch() }).fetcher);
        expect(picks(running).every((box) => box.disabled)).toBe(true);
        expect((q(running, 'offload-restore-selected') as HTMLButtonElement).disabled).toBe(true);
    });

    test('select all covers every offloaded row, also the pages not read yet, and restore selected names them all', async () => {
        const C2 = row({ session_uuid: 'S3', title: 'third' });
        const { fetcher, calls } = harness([[A], [B], [C2]]);
        const el = await render(fetcher);
        expect(picks(el)).toHaveLength(1);
        await click(el.querySelector('[data-tm="offload-select-all"]'));
        expect(picks(el)).toHaveLength(3);
        expect(picks(el).every((box) => box.checked)).toBe(true);
        await click(q(el, 'offload-restore-selected'));
        expect(calls.find((c) => c.method === 'POST')).toMatchObject({ body: { session_uuids: ['S1', 'S2', 'S3'], conversation_ids: [] } });
    });

    test('a row still being offloaded or restored cannot be picked and select all skips it', async () => {
        const el = await render(harness([[A, row({ session_uuid: 'S2', state: 'offloading' }), row({ session_uuid: 'S3', state: 'restoring' })]]).fetcher);
        expect(picks(el).map((box) => box.disabled)).toEqual([false, true, true]);
        await click(el.querySelector('[data-tm="offload-select-all"]'));
        expect(picks(el).map((box) => box.checked)).toEqual([true, false, false]);
    });

    test('the failed targets of the newest bulk restore are listed with their reasons', async () => {
        const items = [
            { kind: 'session', id: 'S1', status: 'restored', code: '', detail: '' },
            { kind: 'session', id: 'S9', status: 'failed', code: 'unknown_session', detail: 'no session S9' },
            { kind: 'conversation', id: 'cccccccc-1111', status: 'failed', code: 'no_vault_point', detail: '' },
        ];
        const el = await render(harness([[A]], { restoreBatch: restoreBatch({ state: 'done', items }) }).fetcher);
        const why = [...el.querySelectorAll('[data-tm="restore-batch-why"]')].map((n) => n.textContent);
        expect(why).toEqual(['S9: no session S9', 'cccccccc-1111: no_vault_point']);
    });
});

/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import SessionsPage from './SessionsPage.svelte';
import type { HistoryApi, HistoryPage } from '../projects-shared/history-api';
import { group, session } from '../projects-shared/test-fixtures';
import { setLocale } from '../i18n/index.svelte';
import { closeItemMenu } from '../item-menu/open.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

installPopoverPolyfill();

setLocale('en');

const NOW = Date.UTC(2026, 9, 14, 12, 0, 0);

const GROUP = group({
    name: 'alpha',
    key: '1',
    session_total: 3,
    counts: { running: 1, asleep: 2 },
    sessions: [
        session({ session_uuid: 'c1', title: 'claude one', label: 'claude one', state: 'running', agent_family: 'claude', live_session_id: 'ses_1' }),
        session({ session_uuid: 'x1', title: 'codex one', label: 'codex one', state: 'asleep', agent_family: 'codex', last_activity_at: '2026-10-01T10:00:00Z' }),
        session({ session_uuid: 's1', title: 'a shell', label: 'a shell', state: 'running', agent_family: 'shell', agent_type: 'shell', kind: 'shell' }),
    ],
});

const PAGE: HistoryPage = { state: 'ok', total: 1, offset: 0, limit: 100, next_offset: null, groups: [GROUP], facets: { agents: [], states: {} } };

function fakeApi(): HistoryApi {
    return { list: vi.fn(() => Promise.resolve(PAGE)) } as unknown as HistoryApi;
}

const readers = { records: () => Promise.resolve([]), counts: () => Promise.resolve({}) };

let handle: ReturnType<typeof mount> | null = null;
afterEach(() => {
    if (handle) void unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

const before = (a: Element, b: Element): boolean => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

describe('SessionsPage shell', () => {
    test('renders the strip in order and counts agent sessions only', async () => {
        const api = fakeApi();
        handle = mount(SessionsPage, { target: document.body, props: { api, readers, embedded: true, now: () => NOW } });
        flushSync();
        await vi.waitFor(() => expect(document.querySelector('.sp-count')?.textContent).toBe('2 of 2'));

        expect((api.list as ReturnType<typeof vi.fn>).mock.calls[0]?.[0]).toContain('agent=claude%2Ccodex');
        expect(document.body.textContent).not.toContain('a shell');

        const q = <T extends Element>(sel: string): T => {
            const el = document.querySelector<T>(sel);
            expect(el, sel).not.toBeNull();
            return el as T;
        };
        const title = q('.oc-titlebar__title');
        const views = [...document.querySelectorAll('[data-view-switch] [data-view]')];
        expect(views.map((b) => b.getAttribute('data-view'))).toEqual(['list', 'pivot', 'timeline']);
        const find = q('.sp-find input[type="search"]');
        const sum = q('.sp-sum');
        expect(title.textContent).toBe('projects');
        expect(before(title, find)).toBe(true);
        expect(before(find, sum)).toBe(true);
        expect(before(views[2]!, q('.sp-count'))).toBe(true);
        expect(q('.sp-find svg')).not.toBeNull();

        expect(q('[data-sum="running"]').textContent).toBe('1');
        expect(q('[data-sum="asleep"]').textContent).toBe('1');
        expect(q('[data-sum="oldest"]').textContent).toBe('13d');

        const states = [...document.querySelectorAll('.sp-seg [data-state]')].map((b) => b.getAttribute('data-state'));
        expect(states).toEqual(['working', 'questions', 'sleep', 'closed', 'archived']);
        const groups = [...document.querySelectorAll('.oc-toolbar__facets > [data-g]')].map((g) => g.getAttribute('data-g'));
        expect(groups).toEqual(['state', 'company', 'project', 'computer', 'provider', 'sort']);
        expect(before(q('.oc-toolbar__facets'), q('.sp-count'))).toBe(true);

        expect(before(q('.sp-bar'), q('.sp-sepbar'))).toBe(true);
        expect([...document.querySelectorAll('.sp-host')].map((h) => [h.getAttribute('data-host'), (h as HTMLElement).hidden])).toEqual([
            ['list', false],
            ['pivot', true],
            ['timeline', true],
        ]);
    });

    test('a page row and a project heading draw no menu button (Joe (ccsliinc), 2026-10-22); the right click is their menu', async () => {
        handle = mount(SessionsPage, { target: document.body, props: { api: fakeApi(), readers, embedded: true, now: () => NOW } });
        flushSync();
        await vi.waitFor(() => expect(document.querySelectorAll('.sp-row').length).toBeGreaterThan(0));
        const rows = [...document.querySelectorAll<HTMLElement>('.sp-row')];
        for (const row of rows) {
            expect(row.querySelector('.session-row-menu-trigger, [data-row-menu], [aria-haspopup]'), `row ${row.dataset.id} has no menu button`).toBeNull();
        }
        for (const head of document.querySelectorAll('.sp-sec-head')) {
            expect(head.querySelector('[aria-haspopup], [data-project-menu]'), 'a heading has no menu button').toBeNull();
        }
        const running = rows.find((r) => r.dataset.id === 'c1')!;
        const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 20, clientY: 20 });
        running.dispatchEvent(event);
        expect(event.defaultPrevented).toBe(true);
        closeItemMenu();
    });

    test('a state button and a provider select narrow the count', async () => {
        handle = mount(SessionsPage, { target: document.body, props: { api: fakeApi(), readers, embedded: true, now: () => NOW } });
        flushSync();
        await vi.waitFor(() => expect(document.querySelector('.sp-count')?.textContent).toBe('2 of 2'));
        expect([...document.querySelectorAll('.sp-seg [aria-pressed="true"]')].map((b) => b.getAttribute('data-state'))).toEqual(['working', 'sleep']);
        document.querySelector<HTMLButtonElement>('[data-state="sleep"]')!.click();
        flushSync();
        expect(document.querySelector('.sp-count')?.textContent).toBe('1 of 2');
    });
});

/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import SessionsPage from './SessionsPage.svelte';
import type { HistoryApi, HistoryPage } from '../projects-shared/history-api';
import { group, session } from '../projects-shared/test-fixtures';
import { setLocale } from '../i18n/index.svelte';
import { closeItemMenu } from '../item-menu/open.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { viewport } from '../../opscenter/engine/viewport.svelte';

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
    viewport.wide = true;
    viewport.phone = false;
    viewport.narrow = false;
});

async function showAt(wide: boolean, narrow: boolean): Promise<HTMLElement> {
    viewport.wide = wide;
    viewport.phone = !wide;
    viewport.narrow = narrow;
    const page = mount(SessionsPage, { target: document.body, props: { api: fakeApi(), readers, embedded: false, now: () => NOW } }) as { show: () => void };
    handle = page;
    page.show();
    flushSync();
    await vi.waitFor(() => expect(document.querySelector('.sp-count')).not.toBeNull());
    return document.querySelector('.sp-page') as HTMLElement;
}

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
        const find = q('.oc-titlebar__find input[type="search"]');
        const sum = q('.sp-sum');
        expect(title.textContent).toBe('projects');
        expect(before(title, sum)).toBe(true);
        expect(before(sum, find)).toBe(true);
        expect(before(views[2]!, q('.sp-count'))).toBe(true);

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

    test('the page wears its nav frame: the find, summary and icon buttons are the frame title strip, at the frame density (#2775, S11)', async () => {
        handle = mount(SessionsPage, { target: document.body, props: { api: fakeApi(), readers, embedded: true, now: () => NOW } });
        flushSync();
        await vi.waitFor(() => expect(document.querySelector('.sp-count')).not.toBeNull());
        const root = document.querySelector('.sp-page') as HTMLElement;
        expect(root.getAttribute('data-frame')).toBe('nav');
        const head = root.querySelector('header.oc-titlebar') as HTMLElement;
        expect(head.getAttribute('data-frame-region')).toBe('header');
        expect(head.getAttribute('data-btn-density')).toBe('frame');
        expect(head.querySelector('.oc-titlebar__find input[type="search"]')).not.toBeNull();
        expect(head.querySelector('.oc-titlebar__sub .sp-sum')).not.toBeNull();
        const acts = [...head.querySelectorAll('.oc-titlebar__actions .sp-acts [data-act]')].map((b) => b.getAttribute('data-act'));
        expect(acts).toEqual(['new-project', 'new-company', 'new-session', 'clean-worktrees', 'show-hidden', 'fold-all']);
        expect(root.querySelectorAll('.pl-title')).toHaveLength(0);
        expect(root.querySelector('[data-frame-region="body"][data-scroll="self"] .sp-body .sp-hosts')).not.toBeNull();
    });

    test('the lens rail is the frame\'s side region and the session panel its detail region, under the one header (#2775, call B and ruling Q1)', async () => {
        history.replaceState(null, '', '#sessions/c1');
        handle = mount(SessionsPage, { target: document.body, props: { api: fakeApi(), readers, embedded: true, now: () => NOW } });
        flushSync();
        await vi.waitFor(() => expect(document.querySelector('[data-frame-region="detail"]')).not.toBeNull());
        const root = document.querySelector('.sp-page') as HTMLElement;
        await vi.waitFor(() => expect(root.querySelector('[data-frame-region="side"] nav.sp-rail')).not.toBeNull());
        expect(root.querySelector('[data-frame-region="side"] nav.sp-rail')).not.toBeNull();
        expect(root.querySelector('.sp-ix .sp-rail')).toBeNull();
        const region = root.querySelector('.oc-page__frame--detail > [data-frame-region="detail"]') as HTMLElement;
        expect(region.querySelector('#sp-pn')).not.toBeNull();
        expect(region.querySelector('.oc-page__detail-title')?.textContent).toBeTruthy();
        expect(root.querySelector('.sp-pn-bar, [data-pn-back], [data-pn-close]')).toBeNull();
        expect(root.firstElementChild?.matches('header.oc-titlebar')).toBe(true);
        expect(root.querySelector('.sp-hosts[data-panel]')).toBeNull();
        (region.querySelector('.oc-page__detail-head [data-btn]') as HTMLButtonElement).click();
        flushSync();
        await vi.waitFor(() => expect(root.querySelector('[data-frame-region="detail"]')).toBeNull());
        history.replaceState(null, '', '#');
    });

    test('on a phone the icon buttons and the fleet summary ride the tool row, so the header keeps room for the find (S11 review)', async () => {
        const root = await showAt(false, true);
        expect(root.querySelector('header .sp-acts')).toBeNull();
        expect(root.querySelector('header .sp-sum')).toBeNull();
        expect(root.querySelector('.oc-page__bar .sp-acts')).not.toBeNull();
        expect(root.querySelector('.oc-page__bar .sp-sum')).not.toBeNull();
    });

    test('from 768 to 1023 the fleet summary rides the tool row, where it is never clipped to one line; the icon buttons stay in the header (S11 review)', async () => {
        const root = await showAt(false, false);
        expect(root.querySelector('header .oc-titlebar__sub .sp-sum')).toBeNull();
        expect(root.querySelector('.oc-page__bar .sp-sum')).not.toBeNull();
        expect(root.querySelector('header .oc-titlebar__actions .sp-acts')).not.toBeNull();
        expect(root.querySelector('.oc-page__bar .sp-acts')).toBeNull();
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

    test('a bar too narrow for its labelled row goes compact: the class is worn and each select\'s "any" option carries its label (fit-bar wiring)', async () => {
        const clientWidth = vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(300);
        const box = vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ width: 200 } as DOMRect);
        vi.stubGlobal('ResizeObserver', class { constructor(private cb: () => void) {} observe() { queueMicrotask(this.cb); } disconnect() {} });
        try {
            handle = mount(SessionsPage, { target: document.body, props: { api: fakeApi(), readers, embedded: true, now: () => NOW } });
            flushSync();
            await vi.waitFor(() => expect(document.querySelector('.sp-bar.sp-bar--compact')).not.toBeNull());
            const company = document.querySelector<HTMLSelectElement>('[data-g="company"] select')!;
            expect(company.options[0]!.textContent).toBe('company');
        } finally {
            clientWidth.mockRestore();
            box.mockRestore();
            vi.unstubAllGlobals();
        }
    });
});

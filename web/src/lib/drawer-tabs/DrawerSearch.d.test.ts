/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import * as Search from '../drawer/search';
import * as Store from '../drawer/store';
import DrawerSearch from './DrawerSearch.svelte';
import { DRAWER_SEARCH_ID, DRAWER_SEARCH_MODE_KEY } from './drawer-tabs';
import { CONTEXT_MODE_ID, MODE_ALL, MODE_NAMES, MODE_PROMPTS } from './search-modes';
import { drawList, loadLegacyDrawer, resetDrawer } from '../sidebar-shell/legacy-fixture';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { searchD } from '../drawer/search-d.svelte';

const calls: string[] = [];
const hit = { line: 3, kind: 'user', snippet: 'we use \u0002carn\u0003ivore here', file_kind: 'conversation', at: '2026-10-15T08:31:00', entry_uuid: 'u-3' };

vi.mock('../../opscenter/api/auth.svelte', async (orig) => ({
    ...(await orig<typeof import('../../opscenter/api/auth.svelte')>()),
    authFetch: (url: string) => {
        calls.push(url);
        if (url.includes('/deepsearch/suggest')) return Promise.resolve({ prefix: 'carn', count: 2, terms: [{ term: 'carnivore', docs: 41 }, { term: 'carnival', docs: 6 }] });
        return Promise.resolve({
            query: 'carn', total_conversations: 5, total_matches: 9, offset: 0, ingest: { state: 'running' },
            groups: [{ conversation_id: 'conv-x', matches: 2, session_uuid: 's-x', session: 'release notes', project: 'carnivore', last_active: '2026-10-15T10:00:00', hits: [hit] }],
        });
    },
}));

const REPO = path.resolve(process.cwd(), '..');
function drawerMarkup(): string {
    const source = fs.readFileSync(path.join(REPO, 'client', 'index.html'), 'utf8');
    const start = source.indexOf('<aside id="session-sidebar-panel"');
    const end = source.indexOf('</aside>', start);
    return source.slice(start, end + '</aside>'.length);
}

const mounted: ReturnType<typeof mount>[] = [];
const rows = (): Record<string, unknown>[] => [
    { name: 'cloude_carn_a', label: null, status: 'idle', project_id: 10, project_name: 'Ledger', working_dir: '/tmp/a', created_by_cloude: true, session_id: null },
    { name: 'cloude_carn_b', label: null, status: 'idle', asleep: true, claude_session_uuid: 'conv-b', project_id: 10, project_name: 'Ledger', working_dir: '/tmp/b', created_by_cloude: true, session_id: null },
];

beforeAll(() => loadLegacyDrawer());
beforeEach(() => {
    installPopoverPolyfill();
    vi.useFakeTimers();
    calls.length = 0;
    document.body.innerHTML = drawerMarkup();
    localStorage.clear();
    resetDrawer();
    Search.setQuery('');
    (globalThis as Record<string, unknown>).SessionSidebarSearch = {
        getQuery: Search.getQuery, setQuery: Search.setQuery, matchesRow: Search.matchesRow,
        matchesLabel: Search.matchesLabel, noMatchesHtml: Search.noMatchesHtml, normalize: Search.normalize,
    };
    Store.save([], rows().map((r) => r.name as string), []);
    localStorage.setItem(DRAWER_SEARCH_MODE_KEY, MODE_ALL);
});
afterEach(async () => {
    for (const m of mounted.splice(0)) await unmount(m);
    vi.useRealTimers();
    Search.setQuery('');
    document.body.replaceChildren();
});

async function typeAndPaint(value: string): Promise<HTMLInputElement> {
    mounted.push(mount(DrawerSearch, { target: document.getElementById(DRAWER_SEARCH_ID)! }));
    flushSync();
    const input = document.querySelector<HTMLInputElement>('.oc-search > input')!;
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    await vi.advanceTimersByTimeAsync(400);
    drawList(rows());
    flushSync();
    await vi.advanceTimersByTimeAsync(10);
    flushSync();
    return input;
}

const press = (input: HTMLElement, key: string, init: KeyboardEventInit = {}): boolean => {
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
    input.dispatchEvent(event);
    flushSync();
    return event.defaultPrevented;
};

test('the clear x is drawn while the box holds text and is NOT focused, and has no hover tile of its own', async () => {
    const input = await typeAndPaint('carn');
    expect(document.activeElement).not.toBe(input);
    const x = document.querySelector<HTMLButtonElement>('.oc-search__clear')!;
    expect(x).not.toBeNull();
    expect(x.getAttribute('aria-label')).toBe('clear search');
    x.click();
    flushSync();
    expect(input.value).toBe('');
    expect(document.querySelector('.oc-search__clear')).toBeNull();
});

test('the similar terms are the context mode only: names, prompts and all show none', async () => {
    for (const mode of [MODE_NAMES, MODE_PROMPTS, MODE_ALL]) {
        localStorage.setItem(DRAWER_SEARCH_MODE_KEY, mode);
        await typeAndPaint('carn');
        expect(document.querySelector('.ds-terms'), `${mode}: no similar terms row`).toBeNull();
        for (const m of mounted.splice(0)) await unmount(m);
        document.querySelector('#' + DRAWER_SEARCH_ID)?.replaceChildren();
    }
    localStorage.setItem(DRAWER_SEARCH_MODE_KEY, CONTEXT_MODE_ID);
    await typeAndPaint('carn');
    expect(document.querySelectorAll('.ds-terms [role="option"]').length, 'context: the terms are there').toBe(2);
});

test('at 2 characters the similar terms appear in the context mode, with counts; arrow down enters them and enter searches the term', async () => {
    localStorage.setItem(DRAWER_SEARCH_MODE_KEY, CONTEXT_MODE_ID);
    const input = await typeAndPaint('carn');
    const chips = [...document.querySelectorAll<HTMLElement>('.ds-terms [role="option"]')];
    expect(chips.map((c) => c.textContent)).toEqual(['carnivore41', 'carnival6']);
    expect(calls.some((u) => u.includes('/deepsearch/suggest'))).toBe(true);
    expect(press(input, 'ArrowDown')).toBe(true);
    expect(chips[0]!.getAttribute('aria-selected')).toBe('true');
    press(input, 'ArrowRight');
    expect(input.getAttribute('aria-activedescendant')).toBe(chips[1]!.id);
    press(input, 'Escape');
    expect(document.querySelectorAll('.ds-terms [role="option"]').length, 'escape returns to the box, the row stays').toBe(2);
    press(input, 'ArrowDown');
    expect(press(input, 'Enter')).toBe(true);
    expect(input.value).toBe('carnivore ');
});

test('one letter shows no terms row', async () => {
    await typeAndPaint('c');
    expect(document.querySelector('.ds-terms')).toBeNull();
});

test('Enter opens the top agent hit as its row\'s click does; the wake-arm path is the row\'s own for an asleep one', async () => {
    const input = await typeAndPaint('carn');
    const list = document.getElementById('session-sidebar-list')!;
    const first = list.querySelector<HTMLElement>('.session-sidebar-row[data-band="search:agents"]')!;
    expect(first.dataset.name).toBe('cloude_carn_a');
    let clicked = 0;
    first.addEventListener('click', () => { clicked += 1; });
    expect(press(input, 'Enter')).toBe(true);
    expect(clicked).toBe(1);
    press(input, 'ArrowDown');
    expect(first.getAttribute('data-search-cursor')).toBeNull();
    const second = list.querySelector<HTMLElement>('.session-sidebar-row[data-name="cloude_carn_b"]')!;
    expect(second.getAttribute('data-search-cursor')).toBe('1');
});

test('a conversation hit shows under AGENTS with its match and no buttons', async () => {
    await typeAndPaint('carn');
    const hitEl = document.querySelector<HTMLElement>('[data-testid="search-conversations"] .dps__hit')!;
    expect(hitEl.querySelector('mark')!.textContent).toBe('carn');
    expect(hitEl.querySelector('.sd-hit__snip mark.sd-mark'), 'the mock\'s excerpt block and bright underlined match').not.toBeNull();
    const head = document.querySelector('[data-search-section="conversations"] .sd-hd')!;
    expect(head.querySelector('.sd-hd__label')!.textContent).toBe('conversations');
    expect(head.querySelector('.sd-hd__n')!.textContent).toBe('5');
    expect(head.querySelector('.sd-hd__chev'), 'a fold chevron').not.toBeNull();
    expect(head.querySelector('.sd-hd__act[data-search-next="conversations"]')!.textContent, 'the deep search link replaces the footer line').toBe('deep search');
    expect(document.querySelector('.ssr-all')).toBeNull();
    expect(hitEl.querySelectorAll('button')).toHaveLength(0);
    expect(hitEl.querySelector('[data-testid="deepsearch-actions"]')).toBeNull();
});

test('each mode searches only its own kind: names lists agents with no conversations, all lists both', async () => {
    localStorage.setItem(DRAWER_SEARCH_MODE_KEY, MODE_NAMES);
    await typeAndPaint('carn');
    expect(document.querySelector('[data-testid="search-conversations"] .dps__hit'), 'names mode shows no conversation hits').toBeNull();
    expect(searchD.controller, 'names mode hands the list no conversation search').toBeNull();
    expect(document.querySelector('[data-search-section="conversations"]'), 'names mode draws no CONVERSATIONS section when agents matched').toBeNull();
    for (const m of mounted.splice(0)) await unmount(m);
    document.body.innerHTML = drawerMarkup();
    localStorage.setItem(DRAWER_SEARCH_MODE_KEY, MODE_ALL);
    await typeAndPaint('carn');
    expect(document.querySelector('[data-testid="search-conversations"] .dps__hit'), 'all mode shows conversation hits').not.toBeNull();
});

/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import * as Search from '../drawer/search';
import DrawerSearch from './DrawerSearch.svelte';
import { DRAWER_DEEP_SEARCH_KEY, DRAWER_SEARCH_ID, DRAWER_SEARCH_MODE_KEY } from './drawer-tabs';
import { CONTEXT_MODE_ID, LEGACY_GREP_MODE, MODE_NAMES, MODE_PROMPTS, PROMPTS_SEARCH_PATH, MODE_ALL } from './search-modes';
import { DATABASE_SEARCH_PATH, DATABASE_SUGGEST_PATH } from '../deepsearch/deepsearch-api';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import '../plugins/builtin';

const apiCalls: string[] = [];

vi.mock('../../opscenter/api/auth.svelte', async (orig) => ({
    ...(await orig<typeof import('../../opscenter/api/auth.svelte')>()),
    authFetch: (url: string) => {
        apiCalls.push(url);
        return Promise.resolve({ query: 'zebra', total_conversations: 0, total_matches: 0, offset: 0, groups: [], ingest: { state: 'running' } });
    },
}));

const REPO = path.resolve(process.cwd(), '..');

/** The drawer's <aside>, exactly as shipped. */
function drawerMarkup(): string {
    const source = fs.readFileSync(path.join(REPO, 'client', 'index.html'), 'utf8');
    const start = source.indexOf('<aside id="session-sidebar-panel"');
    const end = source.indexOf('</aside>', start);
    if (start < 0 || end < 0) throw new Error('the drawer markup is missing from client/index.html');
    return source.slice(start, end + '</aside>'.length);
}

const mounted: ReturnType<typeof mount>[] = [];

beforeEach(() => {
    installPopoverPolyfill();
    vi.useFakeTimers();
    apiCalls.length = 0;
    document.body.innerHTML = drawerMarkup();
    localStorage.clear();
    Search.setQuery('');
    (globalThis as Record<string, unknown>).SessionSidebarSearch = {
        getQuery: Search.getQuery, setQuery: Search.setQuery, matchesRow: Search.matchesRow,
        matchesLabel: Search.matchesLabel, noMatchesHtml: Search.noMatchesHtml, normalize: Search.normalize,
    };
});

afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    vi.useRealTimers();
    document.body.replaceChildren();
    localStorage.clear();
    delete (globalThis as Record<string, unknown>).SessionSidebarSearch;
});

function render() {
    const target = document.getElementById(DRAWER_SEARCH_ID)!;
    mounted.push(mount(DrawerSearch, { target }));
    flushSync();
    const input = target.querySelector<HTMLInputElement>('.oc-search > input')!;
    const button = () => target.querySelector<HTMLButtonElement>('[data-ds-mode]')!;
    const rows = () => Array.from(document.querySelectorAll<HTMLElement>('[role="menuitemradio"]'));
    const choose = (id: string) => {
        button().click();
        flushSync();
        rows().find((r) => r.dataset.node === id)!.click();
        flushSync();
    };
    return { target, input, button, rows, choose };
}

async function type(input: HTMLInputElement, value: string): Promise<void> {
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    await vi.advanceTimersByTimeAsync(400);
    flushSync();
}

test('the dropdown lists exactly names, prompts, context, all: an icon and one word each, nothing else', () => {
    const { button, rows, target } = render();
    expect(button().dataset.mode, 'the default is the name filter').toBe(MODE_NAMES);
    button().click();
    flushSync();
    expect(rows().map((r) => r.dataset.node)).toEqual([MODE_NAMES, MODE_PROMPTS, CONTEXT_MODE_ID, MODE_ALL]);
    expect(rows().map((r) => r.querySelector('.acm-label')!.textContent)).toEqual(['names', 'prompts', 'context', 'all']);
    for (const row of rows()) {
        expect(row.querySelector('.acm-icon svg'), `${row.dataset.node} has an icon`).not.toBeNull();
        expect(row.querySelector('.acm-desc'), `${row.dataset.node} has no second line`).toBeNull();
        expect(row.title, `${row.dataset.node} has no tooltip`).toBe('');
    }
    expect(rows().find((r) => r.dataset.node === MODE_NAMES)!.getAttribute('aria-checked')).toBe('true');
    expect(target.querySelector('[data-action="new-session"]'), 'the + is in the tab bar, not the search row').toBeNull();
});

test('the mode select sits at the right end of the field and the field fills the row', () => {
    const { button } = render();
    const field = button().closest('.oc-search')!;
    expect(field, 'the mode button lives inside the search field').not.toBeNull();
    expect(field.firstElementChild!.classList.contains('oc-search__icon'), 'the search icon stays first on the left').toBe(true);
    expect(field.lastElementChild!.firstElementChild, 'the mode select ends the field (in its trailing slot)').toBe(button());
    expect(field.parentElement!.children.length, 'the row is the field alone').toBe(1);
    const glyphs = [...button().querySelectorAll('svg')];
    expect(glyphs.length).toBe(2);
    expect(glyphs[1]!.getAttribute('width'), 'the arrow comes last').toBe('10');
    expect(button().querySelector('.ds-mode-word'), 'the button shows the icon only').toBeNull();
    expect(button().getAttribute('aria-label')).toContain('names');
});

test('one word goes to three different searches, one per mode', async () => {
    const { input, choose, target } = render();
    await type(input, 'zebra');
    expect(apiCalls.some((u) => u.startsWith(PROMPTS_SEARCH_PATH)), 'names never asks the prompts route').toBe(false);
    apiCalls.length = 0;
    expect(Search.getQuery()).toBe('zebra');

    choose(MODE_PROMPTS);
    await vi.advanceTimersByTimeAsync(400);
    flushSync();
    expect(apiCalls.map((u) => u.split('?')[0])).toEqual([PROMPTS_SEARCH_PATH]);
    expect(apiCalls[0]).toContain('q=zebra');
    expect(target.querySelector('.dps__status')!.textContent).toBe('none of your prompts mention "zebra"');

    choose(CONTEXT_MODE_ID);
    await vi.advanceTimersByTimeAsync(400);
    flushSync();
    expect(apiCalls.slice(1).map((u) => u.replace(/[?&](q|limit|offset|per_group)=[^&]*/g, '').replace(/&/, '?'))).toEqual([
        `${DATABASE_SUGGEST_PATH}`,
        `${DATABASE_SEARCH_PATH}?scope=peers`,
        `${DATABASE_SEARCH_PATH}?scope=local`,
    ]);
    expect(target.querySelector('.dps__status')!.textContent).toBe('no conversation mentions "zebra"');
});

test('the chosen mode is remembered per device and survives a new mount', async () => {
    const first = render();
    first.choose(MODE_PROMPTS);
    expect(localStorage.getItem(DRAWER_SEARCH_MODE_KEY)).toBe(MODE_PROMPTS);
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.innerHTML = drawerMarkup();
    const second = render();
    expect(second.button().dataset.mode).toBe(MODE_PROMPTS);
    expect(second.input.getAttribute('aria-label')).toBe('search only the prompts you typed, in every saved conversation');
});

test('a remembered grep (the retired transcripts mode) reads as context; nothing is written', () => {
    localStorage.setItem(DRAWER_SEARCH_MODE_KEY, LEGACY_GREP_MODE);
    expect(render().button().dataset.mode).toBe(CONTEXT_MODE_ID);
    expect(localStorage.getItem(DRAWER_SEARCH_MODE_KEY)).toBe(LEGACY_GREP_MODE);
});

test('a #428 deep toggle left on, with no mode ever chosen, lands on context', () => {
    localStorage.setItem(DRAWER_DEEP_SEARCH_KEY, '1');
    expect(render().button().dataset.mode).toBe(CONTEXT_MODE_ID);
});

test('Escape closes the dropdown and focus returns to its button', () => {
    const { button, rows } = render();
    button().click();
    flushSync();
    expect(rows().length).toBe(4);
    rows()[0]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    flushSync();
    expect(rows().length).toBe(0);
});

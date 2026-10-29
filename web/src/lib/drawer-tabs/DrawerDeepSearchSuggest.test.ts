/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import DrawerSearch from './DrawerSearch.svelte';
import { DRAWER_SEARCH_ID, DRAWER_SEARCH_MODE_KEY } from './drawer-tabs';
import { CONTEXT_MODE_ID, CORE_MODES, type SearchModeDef } from './search-modes';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import DeepSearchResults from '../deepsearch/DeepSearchResults.svelte';
import { contextProvider } from '../deepsearch/providers';
import { DEBOUNCE_MS, DeepSearchController } from '../deepsearch/deepsearch.svelte';
import { readAnswer, readSuggestions, type DeepSearchApi } from '../deepsearch/deepsearch-api';
import type { DrawerSearchProvider } from '../deepsearch/provider-types';

const TERMS = readSuggestions({ terms: [{ term: 'zebrafind', docs: 6 }, { term: 'zebrastripe', docs: 2 }, { term: 'zebu', docs: 1 }, { bad: true }] });

let prefixes: string[];
let searches: string[];
const mounted: ReturnType<typeof mount>[] = [];

function database(): SearchModeDef {
    const api: DeepSearchApi = {
        search: async (q) => {
            searches.push(q);
            return readAnswer({ query: q, groups: [], ingest: { state: 'running' } });
        },
        suggest: async (prefix) => {
            prefixes.push(prefix);
            return TERMS;
        },
    };
    const made: DrawerSearchProvider = { ...contextProvider(), create: () => new DeepSearchController(api, async () => 'switched'), Results: DeepSearchResults as DrawerSearchProvider['Results'] };
    return { id: CONTEXT_MODE_ID, icon: 'database', nameKey: 'drawer.search.mode.context', placeholderKey: made.placeholderKey, labelKey: made.labelKey, provider: made };
}

beforeEach(() => {
    installPopoverPolyfill();
    vi.useFakeTimers();
    prefixes = [];
    searches = [];
    document.body.innerHTML = `<aside id="session-sidebar-panel"><div id="${DRAWER_SEARCH_ID}"></div></aside>`;
    localStorage.clear();
    localStorage.setItem(DRAWER_SEARCH_MODE_KEY, CONTEXT_MODE_ID);
    const target = document.getElementById(DRAWER_SEARCH_ID)!;
    mounted.push(mount(DrawerSearch, { target, props: { modes: [CORE_MODES[0]!, database()] } }));
    flushSync();
});

afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    vi.useRealTimers();
    document.body.replaceChildren();
    localStorage.clear();
});

const input = (): HTMLInputElement => document.querySelector<HTMLInputElement>('.oc-search > input')!;
const options = (): HTMLElement[] => Array.from(document.querySelectorAll<HTMLElement>('.ds-terms [role="option"]'));
const selected = (): number => options().findIndex((o) => o.getAttribute('aria-selected') === 'true');

async function type(value: string): Promise<void> {
    input().value = value;
    input().dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS + 1);
    flushSync();
}

function press(k: string): boolean {
    const event = new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true });
    input().dispatchEvent(event);
    flushSync();
    return event.defaultPrevented;
}

test('typing the end of a word asks only after the debounce, for that word alone, and shows the terms as chips with their counts', async () => {
    input().value = 'find zeb';
    input().dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS - 50);
    expect(prefixes, 'still inside the quiet spell').toEqual([]);
    await vi.advanceTimersByTimeAsync(100);
    flushSync();
    expect(prefixes).toEqual(['zeb']);
    expect(options().map((o) => o.textContent!.replace(/\d+$/, ''))).toEqual(['zebrafind', 'zebrastripe', 'zebu']);
    expect(options().map((o) => o.querySelector('.ds-terms__n')!.textContent)).toEqual(['6', '2', '1']);
    expect(document.querySelector('.ds-terms')!.getAttribute('aria-orientation')).toBe('horizontal');
    expect(input().getAttribute('aria-expanded')).toBe('true');
});

test('a one-letter word and a finished word (trailing space) never ask', async () => {
    await type('z');
    await type('zebra ');
    expect(prefixes).toEqual([]);
    expect(options()).toEqual([]);
});

test('arrow down enters the chips, left and right move and wrap, and aria-activedescendant follows', async () => {
    await type('zeb');
    expect(selected()).toBe(-1);
    expect(press('ArrowDown')).toBe(true);
    expect(selected()).toBe(0);
    press('ArrowRight');
    expect(input().getAttribute('aria-activedescendant')).toBe(options()[1]!.id);
    press('ArrowLeft');
    press('ArrowLeft');
    expect(selected(), 'left from the first wraps to the last').toBe(2);
});

test('Enter takes the chip in place of the word and runs the search on the new text', async () => {
    await type('find zeb');
    press('ArrowDown');
    press('ArrowRight');
    expect(press('Enter')).toBe(true);
    expect(input().value).toBe('find zebrastripe ');
    expect(options(), 'the row closes once a term is taken').toEqual([]);
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS + 1);
    expect(searches, 'the typed text searched once, then the completed text').toEqual(['find zeb', 'find zebrastripe']);
});

test('Enter in the box, not on the chips, is left to the results', async () => {
    await type('zeb');
    expect(press('Enter')).toBe(false);
    expect(input().value).toBe('zeb');
});

test('Escape on the chips goes back to the box and keeps the row; the next Escape clears the box', async () => {
    await type('zeb');
    press('ArrowDown');
    expect(press('Escape')).toBe(true);
    expect(options().length, 'the row stays').toBe(3);
    expect(selected()).toBe(-1);
    expect(input().value).toBe('zeb');
    expect(press('Escape')).toBe(true);
    expect(input().value).toBe('');
});

test('a click takes a chip and keeps the box focused', async () => {
    await type('zeb');
    options()[0]!.click();
    flushSync();
    expect(input().value).toBe('zebrafind ');
    expect(document.activeElement).toBe(input());
});

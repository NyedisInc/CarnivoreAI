/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import PageToolbar from './PageToolbar.svelte';
import { readPageView, writePageView } from './page-view';

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
});

const t = (key: string): string => key;

function show(emit: { facets: string[][]; sorts: string[]; views: string[] }, view: 'ledger' | 'cards' = 'ledger'): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(PageToolbar, {
        target,
        props: {
            query: '',
            onQuery: () => {},
            searchPlaceholder: 'search',
            facets: [
                { id: 'project', label: 'project', value: 'all', options: [{ value: 'all', label: 'all' }, { value: 'x', label: 'x' }] },
                { id: 'agent', label: 'agent', value: 'all', options: [{ value: 'all', label: 'all' }, { value: 'claude', label: 'claude' }] },
            ],
            onFacet: (id: string, value: string) => emit.facets.push([id, value]),
            sort: { label: 'sort', value: 'recent', options: [{ value: 'recent', label: 'recent' }, { value: 'name', label: 'name' }] },
            onSort: (value: string) => emit.sorts.push(value),
            view,
            onView: (next: string) => emit.views.push(next),
            t,
        },
    });
    flushSync();
    return target;
}

describe('PageToolbar', () => {
    test('draws search, facets, sort, toggle in the fixed order', () => {
        const root = show({ facets: [], sorts: [], views: [] });
        const parts = [...root.querySelectorAll<HTMLElement>('.oc-toolbar input[type=search], .oc-toolbar .oc-facet, .oc-toolbar .oc-page__view')];
        const names = parts.map((el) => (el.matches('input') ? 'search' : el.matches('.oc-page__view') ? 'toggle' : el.querySelector('.oc-facet__key')!.textContent));
        expect(names).toEqual(['search', 'project', 'agent', 'sort', 'toggle']);
    });

    test('a facet change and a sort change emit', () => {
        const emit = { facets: [] as string[][], sorts: [] as string[], views: [] as string[] };
        const root = show(emit);
        const selects = root.querySelectorAll<HTMLSelectElement>('select.oc-facet__select');
        selects[1]!.value = 'claude';
        selects[1]!.dispatchEvent(new Event('change', { bubbles: true }));
        selects[2]!.value = 'name';
        selects[2]!.dispatchEvent(new Event('change', { bubbles: true }));
        expect(emit.facets).toEqual([['agent', 'claude']]);
        expect(emit.sorts).toEqual(['name']);
    });

    test('the toggle emits the other view', () => {
        const emit = { facets: [] as string[][], sorts: [] as string[], views: [] as string[] };
        const root = show(emit, 'ledger');
        const pressed = root.querySelectorAll<HTMLButtonElement>('.oc-page__view button');
        expect(pressed[1]!.getAttribute('aria-pressed')).toBe('true');
        pressed[0]!.click();
        expect(emit.views).toEqual(['cards']);
    });
});

describe('page view memory', () => {
    test('default, remember, bad value, storage that throws', () => {
        const store = new Map<string, string>();
        vi.stubGlobal('localStorage', { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) });
        expect(readPageView('sessions', 'ledger')).toBe('ledger');
        writePageView('sessions', 'cards');
        expect(readPageView('sessions', 'ledger')).toBe('cards');
        expect(readPageView('skills', 'cards')).toBe('cards');
        store.set('carnivore.pageview.skills', 'bogus');
        expect(readPageView('skills', 'cards')).toBe('cards');
        vi.stubGlobal('localStorage', {
            getItem: () => {
                throw new Error('blocked');
            },
            setItem: () => {
                throw new Error('blocked');
            },
        });
        expect(readPageView('sessions', 'ledger')).toBe('ledger');
        expect(() => writePageView('sessions', 'cards')).not.toThrow();
    });
});

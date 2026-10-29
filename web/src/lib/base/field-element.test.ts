/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync } from 'svelte';

import FieldBind from './FieldBind.fixture.svelte';
import { cleanup, show } from './test-helpers';

afterEach(cleanup);

describe('Field element, bound', () => {
    test('every variant binds its own input or textarea; the search variant keeps the legacy input binding on the same node', () => {
        const seen: Record<string, HTMLElement | null> = {};
        const root = show(FieldBind, { seen });
        flushSync();
        expect(seen.plain).toBe(root.querySelector('input#' + (root.querySelector('label')!.getAttribute('for') ?? '')));
        expect(seen.area).toBe(root.querySelector('textarea'));
        expect(seen.bare).toBe(root.querySelector('input[aria-label="bare"]'));
        expect(seen.search).toBe(root.querySelector('.oc-search input'));
        expect(seen.legacy).toBe(seen.search);
    });

    test('the bound search input takes focus back when the x empties the box', () => {
        const seen: Record<string, HTMLElement | null> = {};
        const root = show(FieldBind, { seen });
        flushSync();
        root.querySelector<HTMLButtonElement>('.oc-search__clear')!.click();
        flushSync();
        expect(document.activeElement).toBe(seen.search);
    });
});

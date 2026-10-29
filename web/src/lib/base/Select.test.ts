/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { createRawSnippet, flushSync } from 'svelte';

import Select, { isGroup } from './Select.svelte';
import { cleanup, show } from './test-helpers';

afterEach(cleanup);

const OPTIONS = [
    { value: '', label: 'all kinds' },
    { value: 'chart', label: 'chart' },
    { value: 'note', label: 'note', disabled: true },
];

const pick = (props: Record<string, unknown> = {}) => {
    const root = show(Select, { options: OPTIONS, 'aria-label': 'kind', ...props });
    return { root, select: root.querySelector('select')! };
};

describe('Select', () => {
    test('a native select carrying the base field marker and no class', () => {
        const { select } = pick();
        expect(select.tagName).toBe('SELECT');
        expect(select.hasAttribute('data-field')).toBe(true);
        expect(select.getAttribute('class')).toBeNull();
        expect(select.hasAttribute('data-size')).toBe(false);
        expect(select.getAttribute('aria-label')).toBe('kind');
        expect([...select.options].map((o) => [o.value, o.textContent, o.disabled])).toEqual([
            ['', 'all kinds', false], ['chart', 'chart', false], ['note', 'note', true],
        ]);
    });

    test('the value is shown, changes flow out through onchange, and set values reflect', () => {
        const seen: string[] = [];
        const { select } = pick({ value: 'chart', onchange: (e: Event) => seen.push((e.currentTarget as HTMLSelectElement).value) });
        expect(select.value).toBe('chart');
        select.value = '';
        select.dispatchEvent(new Event('change', { bubbles: true }));
        flushSync();
        expect(seen).toEqual(['']);
    });

    test('sm writes the small field attribute', () => {
        expect(pick({ size: 'sm' }).select.dataset.size).toBe('sm');
    });

    test('groups draw optgroups; children replace the data', () => {
        const grouped = pick({ options: [{ group: 'live', options: [{ value: 'a', label: 'a' }] }, { value: 'b', label: 'b' }] });
        expect(grouped.select.querySelector('optgroup')?.label).toBe('live');
        expect(isGroup({ group: 'x', options: [] })).toBe(true);
        expect(isGroup({ value: 'x', label: 'x' })).toBe(false);
        const slot = pick({ options: undefined, children: createRawSnippet(() => ({ render: () => '<option value="z">zed</option>' })) });
        expect(slot.select.options[0]!.value).toBe('z');
    });

    test('labelled: a column with a real label, help, and an error that sets aria-invalid and is announced', () => {
        const { root, select } = pick({ label: 'kind', 'aria-label': undefined, help: 'which widgets to list', error: 'pick one', id: 'k' });
        expect(root.querySelector('.oc-form-field')).not.toBeNull();
        expect(root.querySelector('label')?.getAttribute('for')).toBe('k');
        expect(select.id).toBe('k');
        expect(select.getAttribute('aria-invalid')).toBe('true');
        expect(select.getAttribute('aria-describedby')).toBe('k-help k-error');
        expect(root.querySelector('[role="alert"]')?.textContent).toBe('pick one');
    });

    test('unlabelled draws the bare select with no wrapper; disabled and name pass through', () => {
        const { root, select } = pick({ disabled: true, name: 'kind' });
        expect(root.querySelector('.oc-form-field')).toBeNull();
        expect(select.disabled).toBe(true);
        expect(select.name).toBe('kind');
    });
});

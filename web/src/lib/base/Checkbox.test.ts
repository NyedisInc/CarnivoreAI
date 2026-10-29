/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { createRawSnippet, flushSync } from 'svelte';

import Checkbox from './Checkbox.svelte';
import { cleanup, sheet, show } from './test-helpers';

afterEach(cleanup);

const box = (props: Record<string, unknown> = {}) => {
    const root = show(Checkbox, { label: 'enabled', ...props });
    return { root, label: root.querySelector('label')!, input: root.querySelector('input')! };
};

describe('Checkbox', () => {
    test('a native checkbox inside its label, named by the label text', () => {
        const { label, input } = box();
        expect(input.type).toBe('checkbox');
        expect(input.className).toBe('oc-pick__input');
        expect(label.classList.contains('oc-pick')).toBe(true);
        expect(label.textContent?.trim()).toBe('enabled');
        expect(input.checked).toBe(false);
    });

    test('a click on the label toggles the input and reports the change', () => {
        const seen: boolean[] = [];
        const { label, input } = box({ onchange: (e: Event) => seen.push((e.currentTarget as HTMLInputElement).checked) });
        label.click();
        flushSync();
        expect(input.checked).toBe(true);
        input.click();
        flushSync();
        expect(input.checked).toBe(false);
        expect(seen).toEqual([true, false]);
    });

    test('indeterminate is the dom flag, cleared by the first click', () => {
        const { input } = box({ indeterminate: true });
        expect(input.indeterminate).toBe(true);
        input.click();
        flushSync();
        expect(input.indeterminate).toBe(false);
        expect(input.checked).toBe(true);
    });

    test('disabled disables the input and marks the row', () => {
        const { label, input } = box({ disabled: true });
        expect(input.disabled).toBe(true);
        expect(label.hasAttribute('data-disabled')).toBe(true);
        input.click();
        expect(input.checked).toBe(false);
    });

    test('the label slot replaces the string, a hint adds a second line, attributes reach the input', () => {
        const { root, input } = box({
            label: undefined,
            hint: 'sent at once',
            children: createRawSnippet(() => ({ render: () => '<b data-slot>enabled</b>' })),
            name: 'enabled', value: 'yes', 'aria-describedby': 'why', 'data-probe': '1',
        });
        expect(root.querySelector('[data-slot]')).not.toBeNull();
        expect(root.querySelector('.oc-pick__hint')?.textContent).toBe('sent at once');
        expect(input.name).toBe('enabled');
        expect(input.value).toBe('yes');
        expect(input.getAttribute('aria-describedby')).toBe('why');
        expect(input.dataset.probe).toBe('1');
    });

    test('with no visible text the row draws no text column (the caller passes aria-label)', () => {
        const { root, input } = box({ label: undefined, 'aria-label': 'select row' });
        expect(root.querySelector('.oc-pick__text')).toBeNull();
        expect(input.getAttribute('aria-label')).toBe('select row');
    });
});

describe('pick.css', () => {
    const rules = sheet('pick.css');
    test('the checked box fills with the confirm token and a mixed one draws a dash, radios do not take the mixed look', () => {
        const checked = rules.find((r) => r.selector === ".oc-pick__input[type='checkbox']:checked")!;
        expect(checked.decls['background-image']).toContain('var(--oc-green)');
        const mixed = rules.find((r) => r.selector === ".oc-pick__input[type='checkbox']:indeterminate")!;
        expect(mixed.decls['background-size']).toBe('50% var(--oc-space-0-5)');
        expect(rules.some((r) => /(^|[^\]])\:indeterminate/.test(r.selector.replace(/\[type='checkbox'\]:indeterminate/g, '')))).toBe(false);
    });

    test('the box keeps its 1px border for the shared focus rule and carries no literal', () => {
        const input = rules.find((r) => r.selector === '.oc-pick__input')!;
        expect(input.decls.border).toBe('var(--oc-border) solid var(--oc-line-control)');
        expect(input.decls['--_bd']).toBe('var(--oc-line-control)');
        const text = rules.map((r) => Object.values(r.decls).join(' ')).join(' ');
        expect(text).not.toMatch(/#[0-9a-f]{3,8}\b|rgb\(|\d+px/i);
    });
    test('the mark lines up with the first line of the label at every width: no phone rule centers it, and the thumb height pads the text instead', () => {
        const phone = rules.filter((r) => r.within.some((w) => w.startsWith('@media')));
        const centered = phone.filter((r) => Object.values(r.decls).some((v) => v === 'center') && /oc-pick/.test(r.selector));
        expect(centered).toEqual([]);
        const markNudge = phone.find((r) => r.selector === '.oc-pick__input');
        expect(markNudge?.decls['margin-top']).toBeUndefined();
        const row = phone.find((r) => r.selector === '.oc-pick')!;
        expect(row.decls['min-height']).toBe('var(--oc-tap)');
        expect(row.decls['padding-block']).toBe('calc((var(--oc-tap) - 1lh) / 2)');
    });
});

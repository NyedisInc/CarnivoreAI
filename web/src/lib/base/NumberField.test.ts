/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync } from 'svelte';

import NumberField from './NumberField.svelte';
import { cleanup, press, sheet, show } from './test-helpers';

afterEach(cleanup);

const field = (props: Record<string, unknown> = {}) => {
    const root = show(NumberField, { 'aria-label': 'top', ...props });
    const input = root.querySelector<HTMLInputElement>('input')!;
    const [minus, plus] = [...root.querySelectorAll<HTMLButtonElement>('button')] as [HTMLButtonElement, HTMLButtonElement];
    return { root, input, minus, plus };
};

describe('NumberField', () => {
    test('a number input carrying the base field marker, with its bounds and step', () => {
        const { root, input } = field({ value: 5, min: 1, max: 10, step: 2 });
        expect(input.type).toBe('number');
        expect(input.hasAttribute('data-field')).toBe(true);
        expect(input.getAttribute('class')).toBeNull();
        expect([input.min, input.max, input.step, input.value]).toEqual(['1', '10', '2', '5']);
        expect(root.querySelectorAll('button').length).toBe(0);
    });

    test('the stepper adds a labelled minus and plus (base icon buttons) that step and report', () => {
        const seen: (number | null)[] = [];
        const { input, minus, plus } = field({ value: 5, min: 1, max: 7, step: 2, stepper: true, onchange: (v: number | null) => seen.push(v) });
        expect(minus.getAttribute('aria-label')).toBe('decrease');
        expect(plus.getAttribute('aria-label')).toBe('increase');
        expect(minus.dataset).toMatchObject({ btn: 'secondary', size: 'icon' });
        expect(minus.tabIndex).toBe(-1);
        plus.click();
        flushSync();
        expect(input.value).toBe('7');
        expect(plus.disabled).toBe(true);
        minus.click();
        minus.click();
        flushSync();
        expect(input.value).toBe('3');
        expect(seen).toEqual([7, 5, 3]);
    });

    test('steps clamp to min and max and disable at the bounds', () => {
        const { input, minus, plus } = field({ value: 1, min: 1, max: 3, stepper: true });
        expect(minus.disabled).toBe(true);
        minus.click();
        flushSync();
        expect(input.value).toBe('1');
        plus.click();
        plus.click();
        plus.click();
        flushSync();
        expect(input.value).toBe('3');
        expect(plus.disabled).toBe(true);
    });

    test('ArrowUp and ArrowDown step and are consumed; other keys are left alone', () => {
        const { input } = field({ value: 4, min: 0, max: 10 });
        expect(press(input, 'ArrowUp').defaultPrevented).toBe(true);
        expect(input.value).toBe('5');
        press(input, 'ArrowDown');
        press(input, 'ArrowDown');
        expect(input.value).toBe('3');
        expect(press(input, 'a').defaultPrevented).toBe(false);
        expect(input.value).toBe('3');
    });

    test('a fractional step is free of float drift, and an empty field starts from zero inside the bounds', () => {
        const { input } = field({ value: 0.2, step: 0.1 });
        press(input, 'ArrowUp');
        expect(input.value).toBe('0.3');
        const empty = field({ value: null, min: 2, max: 9 });
        press(empty.input, 'ArrowUp');
        expect(empty.input.value).toBe('2');
    });

    test('typing commits through onchange as a number, and clearing is null, never 0', () => {
        const seen: (number | null)[] = [];
        const { input } = field({ value: 5, onchange: (v: number | null) => seen.push(v) });
        input.value = '8';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        input.value = '';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        flushSync();
        expect(seen).toEqual([8, null]);
    });

    test('a caller keydown runs first and can veto the step', () => {
        const { input } = field({ value: 4, onkeydown: (e: KeyboardEvent) => e.preventDefault() });
        press(input, 'ArrowUp');
        expect(input.value).toBe('4');
    });

    test('disabled blocks the field, the buttons and the arrows', () => {
        const { input, minus, plus } = field({ value: 4, stepper: true, disabled: true });
        expect([input.disabled, minus.disabled, plus.disabled]).toEqual([true, true, true]);
        press(input, 'ArrowUp');
        expect(input.value).toBe('4');
    });

    test('labelled: a real label, help and a live error wired by aria', () => {
        const { root, input } = field({ label: 'top n', 'aria-label': undefined, help: 'rows shown', error: 'too many', id: 'n', size: 'sm' });
        expect(root.querySelector('label')?.getAttribute('for')).toBe('n');
        expect(input.getAttribute('aria-describedby')).toBe('n-help n-error');
        expect(input.getAttribute('aria-invalid')).toBe('true');
        expect(input.dataset.size).toBe('sm');
        expect(root.querySelector('.oc-number')?.getAttribute('data-size')).toBe('sm');
        expect(root.querySelector('[role="alert"]')?.textContent).toBe('too many');
    });
});

describe('number-field.css', () => {
    const rules = sheet('number-field.css');
    test('the buttons take the field height, the spin arrows are dropped, no literal sizes', () => {
        expect(rules.find((r) => r.selector === '.oc-number')!.decls['--oc-ibtn-size']).toBe('var(--oc-control-h)');
        expect(rules.find((r) => r.selector === ".oc-number[data-size='sm']")!.decls['--oc-ibtn-size']).toBe('var(--oc-control-h-sm)');
        expect(rules.some((r) => r.selector.includes('spin-button') && r.decls.appearance === 'none')).toBe(true);
        expect(rules.map((r) => Object.values(r.decls).join(' ')).join(' ')).not.toMatch(/\d+px|#[0-9a-f]{3,8}\b/i);
    });
});

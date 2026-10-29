/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { createRawSnippet, flushSync } from 'svelte';

import Radio from './Radio.svelte';
import RadioGroup from './RadioGroup.svelte';
import { cleanup, show } from './test-helpers';

afterEach(cleanup);

const OPTIONS = [
    { value: 'project', label: 'in a project', hint: 'moves the folder with it' },
    { value: 'folder', label: 'in a folder' },
    { value: 'none', label: 'nowhere', disabled: true },
];

const group = (props: Record<string, unknown> = {}) => {
    const root = show(RadioGroup, { label: 'destination', options: OPTIONS, ...props });
    return { root, el: root.querySelector<HTMLElement>('[role="radiogroup"]')!, inputs: [...root.querySelectorAll('input')] };
};

describe('RadioGroup', () => {
    test('a radiogroup named by its label, one native radio per option, all sharing one name', () => {
        const { el, inputs } = group();
        expect(el.getAttribute('aria-label')).toBe('destination');
        expect(inputs.map((i) => i.type)).toEqual(['radio', 'radio', 'radio']);
        expect(new Set(inputs.map((i) => i.name)).size).toBe(1);
        expect(inputs[0]!.name).not.toBe('');
        expect(inputs.map((i) => i.value)).toEqual(['project', 'folder', 'none']);
        expect(el.textContent).toContain('moves the folder with it');
    });

    test('choosing a radio sets the value, reports it, and unchecks the others', () => {
        const seen: string[] = [];
        const { inputs } = group({ value: 'project', onchange: (v: string) => seen.push(v) });
        expect(inputs.map((i) => i.checked)).toEqual([true, false, false]);
        inputs[1]!.click();
        flushSync();
        expect(inputs.map((i) => i.checked)).toEqual([false, true, false]);
        expect(seen).toEqual(['folder']);
    });

    test('a disabled option and a disabled group cannot be chosen', () => {
        const { inputs } = group({ value: 'project' });
        expect(inputs[2]!.disabled).toBe(true);
        const all = group({ disabled: true, name: 'locked' });
        expect(all.inputs.every((i) => i.disabled)).toBe(true);
        expect(all.inputs.every((i) => i.name === 'locked')).toBe(true);
        expect(all.root.querySelectorAll('label[data-disabled]').length).toBe(3);
    });

    test('horizontal puts the data attribute the sheet reads; an unchosen group has no radio checked', () => {
        const { el, inputs } = group({ orientation: 'horizontal' });
        expect(el.dataset.orientation).toBe('horizontal');
        expect(inputs.some((i) => i.checked)).toBe(false);
    });

    test('a group may be named by an element instead (labelledby)', () => {
        const root = show(RadioGroup, {
            labelledby: 'cap',
            value: 'b',
            children: createRawSnippet(() => ({ render: () => '<span></span>' })),
        });
        expect(root.querySelector('[role="radiogroup"]')?.getAttribute('aria-labelledby')).toBe('cap');
    });
});

describe('Radio', () => {
    test('standalone, it is a native radio with the given name, value and state', () => {
        const root = show(Radio, { value: 'a', name: 'solo', label: 'a', checked: true, 'data-probe': '1' });
        const input = root.querySelector('input')!;
        expect(input.type).toBe('radio');
        expect(input.name).toBe('solo');
        expect(input.value).toBe('a');
        expect(input.checked).toBe(true);
        expect(input.dataset.probe).toBe('1');
        expect(root.querySelector('label')?.textContent?.trim()).toBe('a');
    });

    test('inside a group it takes the name, and the label slot works', () => {
        const root = show(RadioGroup, { label: 'g', name: 'shared', value: 'x', options: [{ value: 'x', label: 'x' }] });
        expect(root.querySelector('input')!.name).toBe('shared');
        const slot = show(Radio, { value: 'y', children: createRawSnippet(() => ({ render: () => '<i data-slot>y</i>' })) });
        expect(slot.querySelector('[data-slot]')).not.toBeNull();
    });
});

/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync } from 'svelte';

import Segmented from './Segmented.svelte';
import { cleanup, press, sheet, show } from './test-helpers';

afterEach(cleanup);

const OPTIONS = [
    { value: 'global', label: 'global', attrs: { 'data-scope': 'global' } },
    { value: 'sessions', label: 'sessions' },
    { value: 'gone', label: 'gone', disabled: true },
    { value: 'both', label: 'both', icon: 'plus' },
];

const seg = (props: Record<string, unknown> = {}) => {
    const root = show(Segmented, { options: OPTIONS, label: 'scope', value: 'global', ...props });
    const group = root.querySelector<HTMLElement>('[role="radiogroup"]')!;
    const items = [...group.querySelectorAll<HTMLButtonElement>('[role="radio"]')];
    return { root, group, items };
};
const checked = (items: HTMLElement[]) => items.map((i) => i.getAttribute('aria-checked'));
const stops = (items: HTMLElement[]) => items.map((i) => i.tabIndex);

describe('Segmented', () => {
    test('a named radiogroup of base buttons with role radio and aria-checked', () => {
        const { group, items } = seg();
        expect(group.getAttribute('aria-label')).toBe('scope');
        expect(group.className).toBe('oc-segmented');
        expect(items.map((i) => i.dataset.btn)).toEqual(['quiet', 'quiet', 'quiet', 'quiet']);
        expect(items.every((i) => i.dataset.size === 'sm' && i.type === 'button')).toBe(true);
        expect(checked(items)).toEqual(['true', 'false', 'false', 'false']);
        expect(items[0]!.dataset.scope).toBe('global');
        expect(items[3]!.querySelector('svg')).not.toBeNull();
        expect(items[2]!.disabled).toBe(true);
    });

    test('one tab stop: the picked option, else the first enabled one', () => {
        expect(stops(seg({ value: 'sessions' }).items)).toEqual([-1, 0, -1, -1]);
        expect(stops(seg({ value: '' }).items)).toEqual([0, -1, -1, -1]);
        expect(stops(seg({ value: 'gone' }).items)).toEqual([0, -1, -1, -1]);
    });

    test('a click chooses, reports once, and moves the tab stop', () => {
        const seen: string[] = [];
        const { items } = seg({ onchange: (v: string) => seen.push(v) });
        items[1]!.click();
        flushSync();
        items[1]!.click();
        flushSync();
        expect(checked(items)).toEqual(['false', 'true', 'false', 'false']);
        expect(stops(items)).toEqual([-1, 0, -1, -1]);
        expect(seen).toEqual(['sessions']);
    });

    test('arrow keys move, choose and focus the next enabled option, wrapping and skipping the disabled one', () => {
        const seen: string[] = [];
        const { items } = seg({ onchange: (v: string) => seen.push(v) });
        items[0]!.focus();
        expect(press(items[0]!, 'ArrowRight').defaultPrevented).toBe(true);
        expect(document.activeElement).toBe(items[1]!);
        press(items[1]!, 'ArrowDown');
        expect(document.activeElement).toBe(items[3]!);
        press(items[3]!, 'ArrowRight');
        expect(document.activeElement).toBe(items[0]!);
        press(items[0]!, 'ArrowLeft');
        expect(document.activeElement).toBe(items[3]!);
        press(items[3]!, 'ArrowUp');
        expect(document.activeElement).toBe(items[1]!);
        expect(seen).toEqual(['sessions', 'both', 'global', 'both', 'sessions']);
        expect(checked(items)).toEqual(['false', 'true', 'false', 'false']);
    });

    test('Home and End go to the ends; other keys are left alone', () => {
        const { items } = seg({ value: 'sessions' });
        press(items[1]!, 'End');
        expect(document.activeElement).toBe(items[3]!);
        press(items[3]!, 'Home');
        expect(document.activeElement).toBe(items[0]!);
        expect(press(items[0]!, 'a').defaultPrevented).toBe(false);
    });

    test('disabled disables every option and the keys do nothing', () => {
        const { items } = seg({ disabled: true });
        expect(items.every((i) => i.disabled)).toBe(true);
        press(items[0]!, 'ArrowRight');
        expect(checked(items)).toEqual(['true', 'false', 'false', 'false']);
    });

    test('md size, fill, labelledby and pass-through attributes', () => {
        const { group, items } = seg({ size: 'md', fill: true, label: undefined, labelledby: 'cap', 'data-scope-filter': '' });
        expect(items.every((i) => !i.hasAttribute('data-size'))).toBe(true);
        expect(group.hasAttribute('data-fill')).toBe(true);
        expect(group.getAttribute('aria-labelledby')).toBe('cap');
        expect(group.hasAttribute('data-scope-filter')).toBe(true);
    });
});

describe('Segmented onreselect', () => {
    test('choosing the picked option again by click reports onreselect and never onchange', () => {
        const again: string[] = [];
        const changed: string[] = [];
        const { items } = seg({ onreselect: (v: string) => again.push(v), onchange: (v: string) => changed.push(v) });
        items[0]!.click();
        expect(again).toEqual(['global']);
        expect(changed).toEqual([]);
        items[1]!.click();
        flushSync();
        expect(again).toEqual(['global']);
        expect(changed).toEqual(['sessions']);
    });

    test('Enter and Space on the picked option reach it as a click (the browser activates a button), and the key handler adds no second call', () => {
        const again: string[] = [];
        const { items } = seg({ onreselect: (v: string) => again.push(v) });
        for (const key of ['Enter', ' ']) {
            press(items[0]!, key);
            items[0]!.click();
        }
        expect(again).toEqual(['global', 'global']);
    });

    test('arrow keys, Home and End never report onreselect, even when they land on the picked option', () => {
        const again: string[] = [];
        const { items } = seg({ value: 'sessions', onreselect: (v: string) => again.push(v) });
        for (const key of ['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp', 'Home', 'End']) {
            press(document.activeElement ?? items[1]!, key);
            flushSync();
        }
        expect(again).toEqual([]);
        const one = seg({ options: [{ value: 'only', label: 'only' }], value: 'only', onreselect: (v: string) => again.push(v) });
        press(one.items[0]!, 'ArrowRight');
        expect(again).toEqual([]);
    });

    test('a disabled group or option never reports onreselect', () => {
        const again: string[] = [];
        const group = seg({ disabled: true, onreselect: (v: string) => again.push(v) });
        group.items[0]!.click();
        const opt = seg({ value: 'gone', onreselect: (v: string) => again.push(v) });
        opt.items[2]!.click();
        expect(again).toEqual([]);
    });
});

describe('Segmented caption and mark', () => {
    test('a caption is a leading label cell outside the options, hidden from assistive tech; the group keeps its label', () => {
        const { group, items } = seg({ caption: 'scope' });
        const cell = group.querySelector('.oc-segmented__caption');
        expect(cell?.textContent).toBe('scope');
        expect(cell?.getAttribute('aria-hidden')).toBe('true');
        expect(group.firstElementChild).toBe(cell);
        expect(items).toHaveLength(4);
        expect(group.getAttribute('aria-label')).toBe('scope');
    });

    test('no caption draws no cell', () => {
        expect(seg().group.querySelector('.oc-segmented__caption')).toBeNull();
    });
});

describe('Segmented iconOnly', () => {
    test('an icon option draws only its icon, and its label is the accessible name and the tip; one without an icon keeps its words', () => {
        const { items } = seg({ iconOnly: true });
        const both = items[3]!;
        expect(both.textContent?.trim()).toBe('');
        expect(both.querySelector('svg')).not.toBeNull();
        expect(both.getAttribute('aria-label')).toBe('both');
        expect(both.getAttribute('title')).toBe('both');
        expect(items[0]!.textContent?.trim()).toBe('global');
        expect(items[0]!.hasAttribute('aria-label')).toBe(false);
    });
});

describe('Segmented option title', () => {
    test('an option carries its own title; it wins over the icon-only label tip, and an option without one keeps today', () => {
        const { items } = seg({ options: [
            { value: 'a', label: 'alpha', title: 'the first one' },
            { value: 'b', label: 'beta', icon: 'search', title: 'second tip' },
            { value: 'c', label: 'gamma', icon: 'search' },
            { value: 'd', label: 'delta' },
        ], iconOnly: true, value: 'a' });
        expect(items[0]!.getAttribute('title')).toBe('the first one');
        expect(items[1]!.getAttribute('title')).toBe('second tip');
        expect(items[1]!.getAttribute('aria-label')).toBe('beta');
        expect(items[2]!.getAttribute('title')).toBe('gamma');
        expect(items[3]!.hasAttribute('title')).toBe(false);
    });
});

describe('segmented.css', () => {
    const rules = sheet('segmented.css');
    test('the picked option is the base picked state and the items are split by hairlines, not cards', () => {
        const picked = rules.find((r) => r.selector === ".oc-segmented > [data-btn][aria-checked='true']")!;
        expect(picked.decls['--_btn-fill']).toBe('var(--oc-state-selected)');
        expect(picked.decls['--_btn-ink']).toBe('var(--oc-text-bright)');
        expect(rules.find((r) => r.selector === '.oc-segmented > [data-btn] + [data-btn]')!.decls['box-shadow']).toContain('var(--oc-line-control)');
        expect(rules.map((r) => Object.values(r.decls).join(' ')).join(' ')).not.toMatch(/\d+px|#[0-9a-f]{3,8}\b/i);
    });
    test('a narrow container never squeezes an option to nothing: the group scrolls inside itself and each option keeps its label', () => {
        const group = rules.find((r) => r.selector === '.oc-segmented')!;
        expect(group.decls['overflow-x']).toBe('auto');
        expect(group.decls['min-width']).toBe('0');
        const item = rules.find((r) => r.selector === '.oc-segmented > [data-btn]')!;
        expect(item.decls['flex']).toBe('0 0 auto');
        expect(item.decls['max-width']).toBe('none');
        expect(item.decls['overflow']).toBe('visible');
        const filled = rules.find((r) => r.selector === '.oc-segmented[data-fill] > [data-btn]')!;
        expect(filled.decls['flex']).toBe('1 0 auto');
    });
});

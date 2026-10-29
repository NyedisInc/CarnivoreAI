/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount, type Component } from 'svelte';

import Accordion from './Accordion.svelte';
import Button from './Button.svelte';
import Card from './Card.svelte';
import Field from './Field.svelte';
import Fold from './Fold.svelte';
import OptionList from './OptionList.svelte';
import Tag from './Tag.svelte';
import { buttonAttrs, tagClass } from './classes';

let mounted: Record<string, unknown>[] = [];

afterEach(() => {
    for (const m of mounted) unmount(m);
    mounted = [];
    document.body.innerHTML = '';
});

const html = (markup: string) => createRawSnippet(() => ({ render: () => markup }));

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function show(component: Component<any>, props: Record<string, unknown>): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(component, { target, props }) as Record<string, unknown>);
    flushSync();
    return target;
}

function press(el: Element, key: string): void {
    el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
    flushSync();
}

describe('classes', () => {
    test('a button is the base layer plus a variant attribute, never a class family', () => {
        expect(buttonAttrs('secondary', 'md')).toEqual({ 'data-btn': 'secondary' });
        expect(buttonAttrs('confirm', 'sm')).toEqual({ 'data-btn': 'confirm', 'data-size': 'sm' });
        expect(buttonAttrs('danger', 'md')).toEqual({ 'data-btn': 'danger' });
        expect(buttonAttrs('quiet', 'sm')).toEqual({ 'data-btn': 'quiet', 'data-size': 'sm' });
        expect(tagClass('neutral')).toBe('oc-tag');
        expect(tagClass('ok')).toBe('oc-tag oc-tag--ok');
    });
});

describe('Button', () => {
    test('a button by default, a link with href, its label and attributes kept', () => {
        let clicks = 0;
        const a = show(Button, { variant: 'confirm', onclick: () => clicks++, 'aria-label': 'save it', children: html('<span>save</span>') });
        const button = a.querySelector('button') as HTMLButtonElement;
        expect(button.getAttribute('class')).toBeNull();
        expect(button.dataset.btn).toBe('confirm');
        expect(button.hasAttribute('data-size')).toBe(false);
        expect(button.type).toBe('button');
        expect(button.getAttribute('aria-label')).toBe('save it');
        button.click();
        expect(clicks).toBe(1);
        const b = show(Button, { href: '#base', children: html('<span>open</span>') });
        expect(b.querySelector('a[data-btn="secondary"]')?.getAttribute('href')).toBe('#base');
    });

    test('disabled stays disabled', () => {
        const a = show(Button, { disabled: true, children: html('<span>off</span>') });
        expect((a.querySelector('button') as HTMLButtonElement).disabled).toBe(true);
    });

    test('two buttons of one variant and size differ only in their label', () => {
        const a = show(Button, { size: 'sm', children: html('<span>take recommendation</span>') });
        const b = show(Button, { size: 'sm', children: html('<span>add a note</span>') });
        const attrs = (el: Element) => [...el.attributes].map((x) => `${x.name}=${x.value}`).filter((x) => !x.startsWith('id=')).sort();
        expect(attrs(a.querySelector('button') as Element)).toEqual(attrs(b.querySelector('button') as Element));
    });
});

describe('Tag', () => {
    test('renders the tone class and the word', () => {
        const a = show(Tag, { tone: 'ok', children: html('<span>rec</span>') });
        expect(a.querySelector('span.oc-tag.oc-tag--ok')?.textContent).toBe('rec');
    });
});

describe('Field', () => {
    test('the label names the input, help and error are described, error marks it invalid', () => {
        const a = show(Field, { label: 'other', help: 'say it in your words', error: 'too long', placeholder: 'other' });
        const input = a.querySelector('input[data-field]') as HTMLInputElement;
        const label = a.querySelector('label') as HTMLLabelElement;
        expect(label.htmlFor).toBe(input.id);
        expect(input.getAttribute('aria-invalid')).toBe('true');
        const described = (input.getAttribute('aria-describedby') ?? '').split(' ');
        expect(described.map((id) => document.getElementById(id)?.textContent)).toEqual(['say it in your words', 'too long']);
    });

    test('multiline renders a textarea, no error leaves it valid', () => {
        const a = show(Field, { label: 'note', multiline: true });
        const area = a.querySelector('textarea[data-field]') as HTMLTextAreaElement;
        expect(area).not.toBeNull();
        expect(area.hasAttribute('aria-invalid')).toBe(false);
        expect(area.hasAttribute('aria-describedby')).toBe(false);
    });
});

describe('Card', () => {
    test('a plain card is one labelled section with no toggle', () => {
        const a = show(Card, { title: 'question', meta: 'needs your answer', children: html('<p>body</p>') });
        const section = a.querySelector('section.oc-card') as HTMLElement;
        const title = a.querySelector('.oc-card__title') as HTMLElement;
        expect(section.getAttribute('aria-labelledby')).toBe(title.id);
        expect(title.getAttribute('role')).toBe('heading');
        expect(a.querySelector('.oc-card__toggle')).toBeNull();
        expect(a.querySelectorAll('.oc-card').length).toBe(1);
    });

    test('a foldable card toggles its body and keeps actions outside the button', () => {
        const a = show(Card, {
            title: 'question', foldable: true, open: true, children: html('<p>body</p>'),
            actions: html('<button type="button" class="oc-btn oc-btn--sm">dismiss</button>'),
        });
        const toggle = a.querySelector('button.oc-card__toggle') as HTMLButtonElement;
        const body = a.querySelector('.oc-card__body') as HTMLElement;
        expect(toggle.getAttribute('aria-controls')).toBe(body.id);
        expect(toggle.getAttribute('aria-expanded')).toBe('true');
        expect(toggle.querySelector('.oc-btn')).toBeNull();
        expect(a.querySelector('.oc-card__actions .oc-btn')).not.toBeNull();
        toggle.click();
        flushSync();
        expect(toggle.getAttribute('aria-expanded')).toBe('false');
        expect(body.hidden).toBe(true);
    });
});

describe('Fold (bits-ui Collapsible)', () => {
    test('the header button announces and toggles the panel it controls', () => {
        const a = show(Fold, { label: 'answer', count: 3, children: html('<p>the answer</p>') });
        const toggle = a.querySelector('button.oc-fold__toggle') as HTMLButtonElement;
        const panelId = toggle.getAttribute('aria-controls') as string;
        expect(toggle.getAttribute('aria-expanded')).toBe('false');
        expect(document.getElementById(panelId)?.hidden).toBe(true);
        toggle.click();
        flushSync();
        expect(toggle.getAttribute('aria-expanded')).toBe('true');
        const panel = document.getElementById(panelId) as HTMLElement;
        expect(panel.hidden).toBe(false);
        expect(panel.classList.contains('oc-fold__panel')).toBe(true);
        expect(panel.textContent).toContain('the answer');
    });
});

describe('Accordion (bits-ui)', () => {
    const items = [{ value: 'a', label: 'first' }, { value: 'b', label: 'second' }, { value: 'c', label: 'third' }];

    test('single keeps one open; headers are headings; arrows move between them', () => {
        const a = show(Accordion, { items, type: 'single', panel: createRawSnippet((item: () => { label: string }) => ({ render: () => `<p>${item().label} panel</p>` })) });
        const toggles = [...a.querySelectorAll('button.oc-fold__toggle')] as [HTMLButtonElement, HTMLButtonElement, HTMLButtonElement];
        expect(toggles).toHaveLength(3);
        expect(a.querySelector('.oc-fold__head')?.getAttribute('role')).toBe('heading');
        toggles[0].click();
        flushSync();
        expect(toggles.map((t) => t.getAttribute('aria-expanded'))).toEqual(['true', 'false', 'false']);
        toggles[1].click();
        flushSync();
        expect(toggles.map((t) => t.getAttribute('aria-expanded'))).toEqual(['false', 'true', 'false']);
        toggles[1].focus();
        press(toggles[1], 'ArrowDown');
        expect(document.activeElement).toBe(toggles[2]);
        press(toggles[2], 'Home');
        expect(document.activeElement).toBe(toggles[0]);
    });
});

describe('OptionList (bits-ui RadioGroup and Checkbox)', () => {
    const options = [
        { value: 'yes', label: 'yes, those stay built in', reason: 'core depends on them', recommended: true },
        { value: 'no', label: 'no, package them all' },
    ];

    test('one choice: a labelled radiogroup, one tab stop, arrows choose, the rec tag shows', () => {
        let picked: unknown = null;
        const a = show(OptionList, {
            options, prompt: 'stay compiled in?', number: 1, tag: 'required', recommendedLabel: 'rec',
            onValueChange: (v: unknown) => (picked = v),
        });
        const group = a.querySelector('[role="radiogroup"]') as HTMLElement;
        const prompt = a.querySelector('.oc-options__prompt') as HTMLElement;
        expect(group.getAttribute('aria-labelledby')).toBe(prompt.id);
        const radios = [...a.querySelectorAll('[role="radio"]')] as [HTMLElement, HTMLElement];
        expect(radios).toHaveLength(2);
        expect(radios[0].querySelector('.oc-tag.oc-tag--ok')?.textContent).toBe('rec');
        expect(radios[0].querySelector('.oc-option__reason')?.textContent).toBe('core depends on them');
        expect(a.querySelector('.oc-options__head .oc-tag')?.textContent).toBe('required');
        expect(radios.filter((r) => r.tabIndex === 0)).toHaveLength(1);
        radios[0].click();
        flushSync();
        expect(picked).toBe('yes');
        expect(radios[0].getAttribute('aria-checked')).toBe('true');
        radios[0].focus();
        press(radios[0], 'ArrowDown');
        expect(document.activeElement).toBe(radios[1]);
        expect(picked).toBe('no');
        expect(radios[1].getAttribute('aria-checked')).toBe('true');
        expect(radios[0].getAttribute('aria-checked')).toBe('false');
    });

    test('several: checkboxes toggle into the value list', () => {
        let picked: unknown = null;
        const a = show(OptionList, { options, multiple: true, prompt: 'which?', onValueChange: (v: unknown) => (picked = v) });
        const boxes = [...a.querySelectorAll('[role="checkbox"]')] as [HTMLElement, HTMLElement];
        expect(boxes).toHaveLength(2);
        boxes[0].click();
        flushSync();
        boxes[1].click();
        flushSync();
        expect(picked).toEqual(['yes', 'no']);
        boxes[0].click();
        flushSync();
        expect(picked).toEqual(['no']);
        expect(boxes[0].getAttribute('aria-checked')).toBe('false');
    });
});

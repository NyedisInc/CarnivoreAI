/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';

import State from './State.svelte';
import { t } from '../i18n/index.svelte';

let mounted: Record<string, unknown>[] = [];
afterEach(() => {
    for (const m of mounted) unmount(m);
    mounted = [];
    document.body.innerHTML = '';
});

const html = (markup: string) => createRawSnippet(() => ({ render: () => markup }));

function state(props: Record<string, unknown>): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(State, { target, props }) as Record<string, unknown>);
    flushSync();
    return target.querySelector('.oc-state')!;
}

test('empty: a status with the caller words, a hint, and no action row when there is no action', () => {
    const el = state({ title: 'no automations yet', hint: 'start from a template' });
    expect(el.dataset.state).toBe('empty');
    expect(el.getAttribute('role')).toBe('status');
    expect(el.querySelector('.oc-state__title')?.textContent).toBe('no automations yet');
    expect(el.querySelector('.oc-state__hint')?.textContent).toBe('start from a template');
    expect(el.querySelector('.oc-state__actions')).toBeNull();
});

test('renders its action: the one-button shortcut calls back', () => {
    let pressed = 0;
    const el = state({ title: 'nothing matches', actionLabel: 'clear filters', onAction: () => pressed++ });
    const button = el.querySelector<HTMLButtonElement>('.oc-state__actions button')!;
    expect(button.textContent).toBe('clear filters');
    expect(button.dataset.btn).toBe('secondary');
    button.click();
    expect(pressed).toBe(1);
});

test('renders its action: a snippet of buttons', () => {
    const el = state({ actions: html('<button type="button" data-new>new</button>') });
    expect(el.querySelector('.oc-state__actions [data-new]')?.textContent).toBe('new');
    expect(el.querySelector('.oc-state__title')?.textContent).toBe(t('base.state.empty'));
});

test('error: an alert, the catalog words, and "try again" for a retry with no label', () => {
    const el = state({ kind: 'error', onAction: () => {} });
    expect(el.getAttribute('role')).toBe('alert');
    expect(el.querySelector('.oc-state__title')?.textContent).toBe(t('base.state.error'));
    expect(el.querySelector('.oc-state__actions button')?.textContent).toBe(t('base.state.retry'));
    expect(t('base.state.retry')).not.toBe('base.state.retry');
});

test('loading: a busy status in the catalog words; inline is a class', () => {
    const el = state({ kind: 'loading', inline: true });
    expect(el.getAttribute('role')).toBe('status');
    expect(el.getAttribute('aria-busy')).toBe('true');
    expect(el.querySelector('.oc-state__title')?.textContent).toBe(t('base.state.loading'));
    expect(el.classList.contains('oc-state--inline')).toBe(true);
});

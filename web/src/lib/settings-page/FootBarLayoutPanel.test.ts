/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import FootBarItemsPanel from './FootBarItemsPanel.svelte';
import FootBarLayoutPanel from './FootBarLayoutPanel.svelte';
import { footBarItems } from './foot-bar-items-store.svelte';
import { footBarLayout } from './foot-bar-layout-store.svelte';
import { footBarOrder, FOOT_BAR_ORDER_DEFAULT } from './foot-bar-order-store.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

afterEach(() => {
    delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge;
    footBarLayout.value = {};
    footBarItems.value = {};
    footBarOrder.value = [...FOOT_BAR_ORDER_DEFAULT];
});

function recordBridge(): unknown[] {
    const written: unknown[] = [];
    (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = {
        read: () => null,
        write: (_f: string, v: unknown) => { written.push(v); return Promise.resolve(v); },
        follow: () => () => {},
    };
    return written;
}

function render(component: typeof FootBarLayoutPanel | typeof FootBarItemsPanel, props: Record<string, unknown> = {}) {
    const target = document.body.appendChild(document.createElement('div'));
    const handle = mount(component as never, { target, props });
    flushSync();
    return { target, handle: handle as Record<string, unknown> };
}

test('collapsed: three full strips are the radios, named in plain words, and picking one writes that half', () => {
    const written = recordBridge();
    const { target, handle } = render(FootBarLayoutPanel, { half: 'collapsed' });

    const radios = [...target.querySelectorAll<HTMLInputElement>('[role="radiogroup"] input[type="radio"]')];
    expect(radios.map((r) => r.closest('label')!.querySelector('.fbl__name')?.textContent)).toEqual(['meters', 'text line', 'nearest limit']);
    expect(radios.map((r) => String(r.checked))).toEqual(['true', 'false', 'false']);
    expect(radios.map((r) => r.closest('label')!.querySelector('.fbs')?.getAttribute('data-layout'))).toEqual(['a', 'b', 'c']);

    radios[2]!.click();
    flushSync();
    expect(written).toEqual([{ collapsed: 'c', open: 'a' }]);
    expect(radios[2]!.checked).toBe(true);
    unmount(handle);
});

test('open: three thumbnail cards then one large preview of the chosen layout, with filled sample rows', () => {
    const written = recordBridge();
    const { target, handle } = render(FootBarLayoutPanel, { half: 'open' });

    const radios = [...target.querySelectorAll<HTMLInputElement>('input[type="radio"]')];
    expect(radios.map((r) => r.closest('label')!.querySelector('.fbl__name')?.textContent)).toEqual(['columns', 'tabs', 'one list']);
    for (const r of radios) expect(r.closest('label')!.querySelector('.ccp'), 'thumbnail').not.toBeNull();

    const large = target.querySelector<HTMLElement>('[role="img"] .ccp')!;
    expect(large.dataset.layout).toBe('a');
    expect(large.querySelectorAll('.ccp-row').length).toBeGreaterThanOrEqual(7);

    radios[1]!.click();
    flushSync();
    expect(written).toEqual([{ collapsed: 'a', open: 'b' }]);
    expect(target.querySelector('[role="img"] .ccp')?.getAttribute('data-layout')).toBe('b');
    expect(target.querySelectorAll('[role="img"] button[role="tab"]').length).toBe(3);
    expect(target.querySelector('label.oc-pick button')).toBeNull();
    unmount(handle);
});

test('open: the large preview is laid out at its design width and scaled to fit, never a clipped full-size render', () => {
    const { target, handle } = render(FootBarLayoutPanel, { half: 'open' });
    const large = target.querySelector<HTMLElement>('[role="img"] .scaled__in')!;
    expect(large, 'large preview sits in a Scaled box').not.toBeNull();
    expect(large.style.width).toBe('1000px');
    expect(large.style.transform).toMatch(/^scale\(/);
    expect(target.querySelector('[role="img"] .scaled')?.getAttribute('aria-hidden')).toBeNull();
    unmount(handle);
});

test('items: hiding an item re-draws every strip at once', () => {
    const { target, handle } = render(FootBarLayoutPanel, { half: 'collapsed' });
    expect(target.querySelectorAll('.fbs [data-item="model"]').length).toBe(3);

    footBarItems.set('model', false);
    flushSync();
    expect(target.querySelectorAll('.fbs [data-item="model"]').length).toBe(0);
    expect(target.querySelectorAll('.fbs [data-item="effort"]').length).toBe(0);
    unmount(handle);
});

test('items grid: a check per item, effort disabled while the model is hidden, and a toggle writes sparse', () => {
    const written = recordBridge();
    const { target, handle } = render(FootBarItemsPanel);

    const checks = [...target.querySelectorAll<HTMLInputElement>('.oc-grid-4 input[type="checkbox"]')];
    expect(checks.length).toBe(8);
    expect(target.querySelector<HTMLInputElement>('.oc-grid-4 input:disabled')).toBeNull();

    checks[0]!.click();
    flushSync();
    expect(written).toEqual([{ model: false }]);
    const effort = [...target.querySelectorAll<HTMLInputElement>('.oc-grid-4 input[type="checkbox"]')][1]!;
    expect(effort.disabled).toBe(true);
    expect(effort.closest('label')!.textContent).toContain('needs model');
    unmount(handle);
});

test('limit order: moving a limit earlier writes the complete order and re-orders every strip', () => {
    const written = recordBridge();
    const layout = render(FootBarLayoutPanel, { half: 'collapsed' });
    const order = render(FootBarItemsPanel);

    const stripOrder = (): (string | undefined)[] =>
        [...layout.target.querySelectorAll('.fbs[data-layout="a"] [data-meter]')].map((m) => (m as HTMLElement).dataset.meter);
    expect(stripOrder()).toEqual(['context', 'window_5h', 'window_7d']);

    const items = order.target.querySelectorAll<HTMLElement>('.oc-order__item');
    (items[1]!.querySelectorAll('button[data-size="icon"]')[0] as HTMLElement).click();
    flushSync();
    expect(written).toEqual([['window_5h', 'context', 'window_7d']]);
    expect(stripOrder()).toEqual(['window_5h', 'context', 'window_7d']);
    unmount(layout.handle);
    unmount(order.handle);
});

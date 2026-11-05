/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('./places-writes', () => ({ addToPlace: vi.fn(), removeFromPlace: vi.fn(), moveInPlace: vi.fn(), resetBars: vi.fn(async () => {}) }));

import WidgetsScreen from './WidgetsScreen.svelte';
import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import { createWidgetsAdapter } from './widgets-adapter';
import { memoryFetcher } from '../item-settings/memory-fetcher';
import { t } from '../i18n/index.svelte';
import type { Fetcher } from '../item-settings/api';
import { stubResizeObserver } from './settings/mock-test-support';

const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto['showPopover'] ??= function () {};
proto['hidePopover'] ??= function () {};

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

test('the settings tab swaps the catalog for the bar settings and the catalog tab brings it back', async () => {
    stubResizeObserver();
    (globalThis as Record<string, unknown>).PreferenceBridge = { read: (f: string) => (f === 'widget_bars' ? { v: 1, bottom: { size: 'compact' } } : null), write: async () => ({ status: 'committed' }), writeMany: async () => ({ status: 'committed' }), follow: () => () => {} };
    const fetcher = memoryFetcher(Object.fromEntries(Object.values(CORE_MANIFESTS).map((m) => [m.id, m.settings ?? null]))) as Fetcher;
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(WidgetsScreen, { target, props: { embedded: true, t, previews: false, adapter: createWidgetsAdapter(t, CORE_MANIFESTS, fetcher, async () => {}, () => {}) } });
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
    await tick();
    flushSync();
    expect(target.querySelector('.wp-settings')).toBeNull();
    target.querySelector<HTMLElement>('[role=tab]:nth-of-type(2)')!.click();
    flushSync();
    expect(target.querySelector('.wp-settings')).not.toBeNull();
    expect(target.querySelector('[role=radio][aria-label="bottom bar size compact, 20px"]')!.getAttribute('aria-checked')).toBe('true');
    target.querySelector<HTMLElement>('[role=tab]:nth-of-type(1)')!.click();
    flushSync();
    expect(target.querySelector('.wp-settings')).toBeNull();
});

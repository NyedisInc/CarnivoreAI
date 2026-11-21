/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import RestorePoints from './RestorePoints.svelte';
import { readPoint } from './points-api';
import { setLocale, t } from '../../lib/i18n/index.svelte';

setLocale('en');

const BASE = { id: 'p1', created_at: '2026-10-01T10:00:00Z', reason: 'import', packed_bytes: 1048576, raw_bytes: 4194304 };
const mounted: Array<Record<string, unknown>> = [];

function draw(raw: Record<string, unknown>): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    const point = readPoint({ ...BASE, ...raw })!;
    mounted.push(mount(RestorePoints, { target, props: { points: [point], keep: 10, usedBytes: 0, capBytes: 0, busy: new Set<string>(), t, onPin: () => undefined, onRestore: () => undefined } }));
    flushSync();
    return target;
}

afterEach(() => {
    for (const m of mounted.splice(0)) unmount(m);
    document.body.innerHTML = '';
});

describe('an imported point', () => {
    test('renders its imported chip and one chip per label', () => {
        const root = draw({ imported: true, labels: ['junk-20260930:trivial', 'trash-20261016:a06'] });
        expect(root.querySelector('[data-imported]')!.textContent).toBe('imported');
        expect([...root.querySelectorAll('[data-label]')].map((e) => e.textContent)).toEqual(['junk-20260930:trivial', 'trash-20261016:a06']);
    });

    test('an ordinary point shows neither chip', () => {
        const root = draw({ reason: 'kill' });
        expect(root.querySelector('[data-point-id="p1"]')).not.toBeNull();
        expect(root.querySelector('[data-imported]')).toBeNull();
        expect(root.querySelectorAll('[data-label]').length).toBe(0);
    });
});

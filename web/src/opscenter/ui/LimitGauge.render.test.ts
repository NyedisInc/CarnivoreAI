/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import LimitGauge from './LimitGauge.svelte';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const mounted: Array<Record<string, unknown>> = [];

function draw(props: Record<string, unknown>): HTMLElement {
    const host = document.createElement('div');
    document.body.appendChild(host);
    mounted.push(mount(LimitGauge, { target: host, props: props as never }));
    flushSync();
    return host;
}

afterEach(() => {
    while (mounted.length) unmount(mounted.pop() as never);
    document.body.innerHTML = '';
});

describe('LimitGauge', () => {
    test('a known elapsed fraction draws ONE vertical marker at that position', () => {
        const host = draw({ variant: 'fill', pct: 32, scale: 1, paceElapsedPct: 60, meterText: '5h: 32% used' });
        const root = host.querySelector('.oc-gauge') as HTMLElement;
        const markers = root.querySelectorAll('.oc-gauge__pace');
        expect(markers.length).toBe(1);
        expect((markers[0] as HTMLElement).style.left).toBe('60%');
        expect(root.querySelector('.oc-gauge__pace-fill')).toBeNull();
        expect(root.querySelector('.oc-gauge__pace-notch')).toBeNull();
        expect(root.style.getPropertyValue('--oc-gauge-pace-over')).toBe('0px');
        expect((root.querySelector('.oc-gauge__fill') as HTMLElement).style.width).toBe('32%');
        expect(root.getAttribute('data-scale')).toBe('1');
        expect(root.getAttribute('role')).toBe('img');
        expect(root.getAttribute('aria-label')).toBe('5h: 32% used');
        expect(root.hasAttribute('title')).toBe(false);
    });

    test('the marker never reaches past the bar, compact or not', () => {
        const host = draw({ variant: 'fill', pct: 10, scale: 1, paceElapsedPct: 40, meterText: 'x', height: 3 });
        const root = host.querySelector('.oc-gauge') as HTMLElement;
        expect(root.style.getPropertyValue('--oc-gauge-pace-over')).toBe('0px');
    });

    test('an unknown elapsed fraction draws NO marker, never a default', () => {
        const host = draw({ variant: 'fill', pct: 32, scale: 1, paceElapsedPct: null, meterText: 'x' });
        expect(host.querySelector('.oc-gauge__pace')).toBeNull();
    });

    test('the segmented form carries the same marker and lights its cells', () => {
        const host = draw({ variant: 'segments', segments: 20, filled: 7, scale: 3, paceElapsedPct: 25, meterText: 'x' });
        expect((host.querySelector('.oc-gauge__pace') as HTMLElement).style.left).toBe('25%');
        expect(host.querySelectorAll('.seg-bar__cell[data-on="1"]').length).toBe(7);
        expect(host.querySelectorAll('[role="img"]').length).toBe(1);
    });

    test('a decorative gauge has no role, no label and no marker', () => {
        const host = draw({ variant: 'segments', segments: 20, filled: 0, scale: null, paceElapsedPct: 50, meterText: 'x', decorative: true });
        const root = host.querySelector('.oc-gauge') as HTMLElement;
        expect(root.getAttribute('role')).toBeNull();
        expect(root.getAttribute('aria-hidden')).toBe('true');
        expect(host.querySelector('.oc-gauge__pace')).toBeNull();
    });

    test('an out of range elapsed fraction is clamped', () => {
        const host = draw({ variant: 'fill', pct: 150, scale: 5, paceElapsedPct: 180, meterText: 'x' });
        expect((host.querySelector('.oc-gauge__pace') as HTMLElement).style.left).toBe('100%');
        expect((host.querySelector('.oc-gauge__fill') as HTMLElement).style.width).toBe('100%');
    });
});

describe('LimitGauge colours', () => {
    test('the bar takes its class from the usage step and the pace line from the pace state, independently', () => {
        const host = draw({ variant: 'fill', pct: 64, scale: 3, paceElapsedPct: 32, paceState: 'over', meterText: 'x' });
        const root = host.querySelector('.oc-gauge') as HTMLElement;
        expect(root.getAttribute('data-scale')).toBe('3');
        expect((root.querySelector('.oc-gauge__pace') as HTMLElement).getAttribute('data-pace')).toBe('over');
        const calm = draw({ variant: 'fill', pct: 10, scale: 1, paceElapsedPct: 50, paceState: 'on', meterText: 'x' });
        const line = calm.querySelector('.oc-gauge__pace') as HTMLElement;
        expect(calm.querySelector('.oc-gauge')?.getAttribute('data-scale')).toBe('1');
        expect(line.getAttribute('data-pace')).toBe('on');
    });
    test('a pace line with no pace state stays neutral', () => {
        const host = draw({ variant: 'fill', pct: 10, scale: 1, paceElapsedPct: 50, meterText: 'x' });
        expect((host.querySelector('.oc-gauge__pace') as HTMLElement).getAttribute('data-pace')).toBe('');
    });
    test('the pace line is the bright text token for every state, never a pace colour', () => {
        const css = readFileSync(resolve(__dirname, '..', 'controls.css'), 'utf8');
        expect(css).toMatch(/--oc-gauge-pace-color:\s*var\(--oc-text-bright\)/);
        expect(css).not.toMatch(/\[data-pace=/);
    });
});

describe('LimitGauge stylesheet', () => {
    test('every --oc-* token the gauge rules read is defined by the token sheet (an undefined token drew the pace line as nothing)', () => {
        const dir = resolve(__dirname, '..');
        const css = readFileSync(resolve(dir, 'controls.css'), 'utf8');
        const tokens = readFileSync(resolve(dir, 'tokens.css'), 'utf8');
        const start = css.indexOf('.oc-gauge {');
        const end = css.indexOf('@layer patterns');
        expect(start).toBeGreaterThan(0);
        const block = css.slice(start, end);
        expect(block).toContain('.oc-gauge__pace {');
        const local = new Set(['--oc-gauge-h', '--oc-gauge-pace-over', '--oc-gauge-fill', '--oc-gauge-ok', '--oc-gauge-pace-color', '--oc-gauge-ring', '--oc-gauge-track', '--oc-space-1']);
        const used = [...block.matchAll(/var\((--oc-[a-z0-9-]+)/g)].map((m) => m[1] as string).filter((t) => !local.has(t));
        expect(used.length).toBeGreaterThan(3);
        for (const t of used) expect(tokens, t).toContain(`${t}:`);
    });
});

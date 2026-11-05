/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import MockLayout from './MockLayout.svelte';
import { t } from '../../i18n/index.svelte';
import { stubResizeObserver } from './mock-test-support';

let mounted: Record<string, unknown> | null = null;
const css = (): string => readFileSync(resolve(__dirname, 'mock.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

beforeEach(() => stubResizeObserver());
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

describe('MockLayout', () => {
    test('a named frame holds a scaled stage of two cells, each a title strip over an edged body with sample text', async () => {
        mounted = mount(MockLayout, { target: document.body, props: { sidePx: 36, bottomPx: 20, label: 'right bar and bottom bar', t } });
        await tick();
        flushSync();
        const frame = document.querySelector('.wp-mock')!;
        expect(frame.getAttribute('aria-label')).toBe('right bar and bottom bar');
        const stage = frame.querySelector<HTMLElement>('.wp-mock__stage')!;
        expect(stage.style.width).toBe('1280px');
        expect(stage.style.height).toBe('640px');
        expect(stage.style.getPropertyValue('--mock-side')).toBe('36px');
        expect(stage.style.getPropertyValue('--mock-bottom')).toBe('20px');
        const cells = frame.querySelectorAll('.wp-mock__cell');
        expect(cells).toHaveLength(2);
        for (const cell of cells) {
            expect(cell.querySelector(':scope > .wp-mock__head')).not.toBeNull();
            expect(cell.querySelector(':scope > .wp-mock__body > .wp-mock__lines')?.textContent).toContain('sample terminal output');
        }
        expect(frame.querySelector('.wp-mock__cells')?.getAttribute('aria-hidden')).toBe('true');
        expect(frame.querySelector('.wp-mock__cell:nth-child(1) > .wp-mock__body')).not.toBeNull();
    });

    test('the frame is outside the transform; the cell body counter-scales its border (rounded up to a whole px), inset and type', () => {
        const rules = css();
        expect(rules).toMatch(/\.wp-mock\s*\{[^}]*padding:\s*var\(--oc-space-2\)[^}]*border:\s*1px solid var\(--wp-line-section\)/);
        expect(rules).toMatch(/\.wp-mock__body\s*\{[^}]*border:\s*round\(up,\s*calc\(1px \* var\(--wp-mock-k\)\),\s*1px\)\s*solid var\(--wp-line-section\)/);
        expect(rules).toMatch(/\.wp-mock__body\s*\{[^}]*padding:\s*calc\(var\(--oc-space-2\) \* var\(--wp-mock-k\)\)/);
        expect(rules).toMatch(/\.wp-mock__lines\s*\{[^}]*font-size:\s*calc\(var\(--oc-fs-label\) \* var\(--wp-mock-k\)\)/);
    });

    test('every border drawn inside the stage is counter-scaled, so a focus edge renders at 1px, and the pin reserves a border for the shared focus rule', () => {
        const rules = css();
        expect(rules).toMatch(/\.wp-mock__stage\s*\{[^}]*--oc-border:\s*round\(up,\s*calc\(1px \* var\(--wp-mock-k\)\),\s*1px\)/);
        expect(rules).toMatch(/\.wp-key\s*\{[^}]*border:\s*var\(--oc-border\) solid transparent/);
        expect(rules).toMatch(/\.wp-try__pin\s*\{[^}]*border:\s*var\(--oc-border\) solid transparent/);
        expect(rules).not.toMatch(/focus-visible/);
    });

    test('the stylesheet names no literal color, so every shipped theme paints the frame', () => {
        expect(css()).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(|oklch\(/);
    });
});

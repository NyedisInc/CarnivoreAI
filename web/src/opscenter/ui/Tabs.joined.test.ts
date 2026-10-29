/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Tabs from './Tabs.svelte';

const CSS = readFileSync(resolve(process.cwd(), 'src/opscenter/ui/tabs.css'), 'utf8');
let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

function strip(joined?: boolean): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(Tabs, {
        target,
        props: {
            tabs: [{ id: 'a', label: 'a' }, { id: 'b', label: 'b' }],
            active: 'a',
            onSelect: () => {},
            label: 'demo',
            idBase: 'jt',
            ...(joined === undefined ? {} : { joined }),
        },
    });
    flushSync();
    return target.querySelector<HTMLElement>('.oc-ptabs')!;
}

function block(selector: string): string {
    const at = CSS.indexOf(selector);
    expect(at, `${selector} is in tabs.css`).toBeGreaterThan(-1);
    return CSS.slice(CSS.indexOf('{', at), CSS.indexOf('}', at));
}

describe('joined tabs', () => {
    test('the joined prop adds the variant class and the default does not', () => {
        expect(strip(true).classList.contains('oc-ptabs--joined')).toBe(true);
        unmount(mounted!);
        mounted = null;
        document.body.innerHTML = '';
        expect(strip().classList.contains('oc-ptabs--joined')).toBe(false);
    });

    test('inside a widget frame the selected tab takes the body ground', () => {
        expect(block('.rail-body .oc-ptabs {')).toContain('--_tab-on: var(--oc-ground-panel)');
        expect(block(".oc-ptab[aria-selected='true'] {")).toContain(
            'background: var(--_tab-on, var(--oc-ground-tab-selected))',
        );
    });

    test('a widget docked in the session rail joins the same way as one in a frame', () => {
        const rule = block('.rail-body .oc-ptabs {');
        expect(CSS).toMatch(/\.oc-frame \.oc-ptabs,\s*\.rail-body \.oc-ptabs \{/);
        expect(rule).toContain('--_tab-on: var(--oc-ground-panel)');
    });

    test('the strip and the other tabs wear the darker joined ground, the strip hairline runs under both', () => {
        const joined = block('.rail-body .oc-ptabs {');
        expect(joined).toContain('--_strip: var(--oc-ground-tabstrip-joined)');
        expect(joined).toContain('--_tab-off: var(--oc-ground-tabstrip-joined)');
        expect(joined).toContain('--_tab-off-hover: var(--oc-ground-tab-joined-hover)');
        expect(joined).toContain('--_tab-clip: padding-box');
        expect(block('.oc-page .oc-ptabs:not(.oc-ptabs--joined)')).toContain('--_strip: initial');
    });

    test('a full page keeps the lighter selected fill', () => {
        expect(block('.oc-page .oc-ptabs:not(.oc-ptabs--joined)')).toContain('--_tab-on: initial');
        expect(CSS).toContain('var(--oc-ground-tab-selected)');
        expect(block('.oc-ptabs {')).not.toContain('--_tab-on');
    });
});

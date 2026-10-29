/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Check from './Check.svelte';

const css = readFileSync('src/opscenter/controls.css', 'utf8');
let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

function show(label: string): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(Check, { target, props: { label, ariaLabel: 'x', checked: false, onToggle: () => {} } });
    flushSync();
    return target.querySelector('button.oc-check') as HTMLElement;
}

function block(selector: string): string {
    const at = css.indexOf(selector);
    expect(at, `${selector} rule exists`).toBeGreaterThan(-1);
    return css.slice(css.indexOf('{', at), css.indexOf('}', at));
}

test('a label-less check wears the bare modifier, a labelled one does not', () => {
    expect(show('').classList.contains('oc-check--bare')).toBe(true);
    unmount(mounted as Record<string, unknown>);
    document.body.innerHTML = '';
    expect(show('   ').classList.contains('oc-check--bare')).toBe(true);
    unmount(mounted as Record<string, unknown>);
    document.body.innerHTML = '';
    expect(show('model').classList.contains('oc-check--bare')).toBe(false);
});

test('the bare modifier hides the frame, hover included; the labelled frame and the box edge stay', () => {
    const bare = block('.oc-check--bare,');
    expect(bare).toContain('border-color: transparent');
    expect(css).toContain('.oc-check--bare:hover:not(:disabled)');
    expect(block('.oc-check {')).toContain('border: 1px solid var(--oc-control-line)');
    expect(block('.oc-check__box {')).toContain('border: 1px solid var(--oc-control-line-hi)');
});

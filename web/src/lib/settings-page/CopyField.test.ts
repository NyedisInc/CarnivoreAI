/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import CopyField from './CopyField.svelte';
import { setLocale, t } from '../i18n/index.svelte';

setLocale('en');

let handle: Record<string, unknown> | null = null;

afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

test('shows the value with its button beside it, and copy writes the value and says copied', async () => {
    let written = '';
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: async (text: string) => void (written = text) }, configurable: true });
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(CopyField, { target, props: { value: 'http://127.0.0.1:8000/mcp', t, valueAttrs: { 'data-x': 'v' }, buttonAttrs: { 'data-x': 'b' } } }) as Record<string, unknown>;
    flushSync();

    const box = target.querySelector('.st-copy')!;
    expect([...box.children].map((c) => c.tagName)).toEqual(['CODE', 'BUTTON']);
    expect(box.querySelector('[data-x="v"]')!.textContent).toBe('http://127.0.0.1:8000/mcp');
    const button = box.querySelector<HTMLButtonElement>('[data-x="b"]')!;
    expect(button.textContent!.trim()).toBe('copy');
    button.click();
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    await tick();
    expect(written).toBe('http://127.0.0.1:8000/mcp');
    expect(button.textContent!.trim()).toBe('copied');
});

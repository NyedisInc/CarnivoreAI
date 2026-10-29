/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

import { mountIconPicker, unmountIconPicker } from './icon-picker-host';

const ID = 'group-icon-picker-mount';

afterEach(() => {
    unmountIconPicker(ID);
    document.body.innerHTML = '';
});

test('mounts the shared picker into the caller\'s container and reports a choice', () => {
    document.body.innerHTML = `<div id="${ID}"></div>`;
    const onChange = vi.fn();
    expect(mountIconPicker(ID, { value: 'flask', onChange })).toBe(true);
    flushSync();
    const host = document.getElementById(ID)!;
    expect(host.querySelector('.icp')).not.toBeNull();
    const cells = Array.from(host.querySelectorAll('[role="option"]'));
    const selected = cells.filter((c) => c.getAttribute('aria-selected') === 'true');
    expect(selected).toHaveLength(1);
    expect(cells.indexOf(selected[0]!)).toBeGreaterThan(0);
    (host.querySelector('[role="option"]:not([aria-selected="true"])') as HTMLElement).click();
    expect(onChange).toHaveBeenCalledTimes(1);
});

test('unmount removes the picker and reports whether one was there', () => {
    document.body.innerHTML = `<div id="${ID}"></div>`;
    mountIconPicker(ID, { value: null, onChange: () => {} });
    flushSync();
    expect(unmountIconPicker(ID)).toBe(true);
    expect(document.getElementById(ID)!.querySelector('.icp')).toBeNull();
    expect(unmountIconPicker(ID)).toBe(false);
});

test('a missing container mounts nothing', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(mountIconPicker('no-such-container', { value: null, onChange: () => {} })).toBe(false);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
});

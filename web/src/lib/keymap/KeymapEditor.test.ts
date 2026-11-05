/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const saved: unknown[] = [];
vi.mock('../zone-shell/preference-field', () => ({
    PreferenceField: class { start(): void {} reload(): void {} },
    savePreference: vi.fn(async (_field: string, value: unknown) => { saved.push(value); return null; }),
}));

import KeymapEditor from './KeymapEditor.svelte';
import { keymapStore } from './keymap-store.svelte';
import { judge } from './keymap-overrides';
import { ALL_ACTIONS, type KeymapAction } from './keymap-view';

let handle: Record<string, unknown> | null = null;
beforeEach(() => { saved.length = 0; keymapStore.overrides = {}; });
afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

const action = (id: string): KeymapAction => ALL_ACTIONS.find((a) => a.id === id)!;

function press(id: string, init: KeyboardEventInit, family: 'mac' | 'other' = 'mac'): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(KeymapEditor, { target, props: { action: action(id), family, close: () => undefined } });
    flushSync();
    window.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init }));
    flushSync();
    return target;
}

const saveButton = (host: HTMLElement): HTMLButtonElement => host.querySelector<HTMLButtonElement>('[data-keymap-save]')!;

test('a chord another action in the same scope holds names that action and blocks the save', () => {
    const host = press('history.back', { key: 'k', code: 'KeyK', metaKey: true });
    expect(host.querySelector('[data-keymap-clash]')?.textContent).toMatch(/command palette|palette/i);
    expect(saveButton(host).disabled).toBe(true);
    saveButton(host).click();
    expect(saved).toEqual([]);
});

test('a chord the app may never take (a bare key that would reach the terminal) is refused and cannot be saved', () => {
    const host = press('history.back', { key: 'q', code: 'KeyQ' });
    expect(host.querySelector('[data-keymap-refused]')).not.toBeNull();
    expect(saveButton(host).disabled).toBe(true);
    saveButton(host).click();
    expect(saved).toEqual([]);
});

test('a free chord saves, and only the override is written', async () => {
    const host = press('history.back', { key: '9', code: 'Digit9', metaKey: true, shiftKey: true });
    expect(host.querySelector('[data-keymap-clash]')).toBeNull();
    expect(host.querySelector('[data-keymap-refused]')).toBeNull();
    expect(saveButton(host).disabled).toBe(false);
    saveButton(host).click();
    await Promise.resolve();
    expect(saved).toEqual([{ mac: { 'history.back': ['shift+cmd+9'] } }]);
});

test('a chord the terminal itself uses (copy, paste, search) is refused, on both keyboards', () => {
    for (const [family, init] of [
        ['other', { key: 'C', code: 'KeyC', ctrlKey: true, shiftKey: true }],
        ['other', { key: 'V', code: 'KeyV', ctrlKey: true, shiftKey: true }],
        ['mac', { key: 'f', code: 'KeyF', metaKey: true }],
    ] as const) {
        const host = press('history.back', init, family);
        expect(host.querySelector('[data-keymap-refused]'), `${family} ${init.key}`).not.toBeNull();
        expect(saveButton(host).disabled).toBe(true);
        unmount(handle!);
        handle = null;
        document.body.innerHTML = '';
    }
    expect(saved).toEqual([]);
});

test('off a mac, ctrl with alt is refused because it types characters on many keyboards', () => {
    const host = press('history.back', { key: 'j', code: 'KeyJ', ctrlKey: true, altKey: true }, 'other');
    expect(host.querySelector('[data-keymap-refused]')).not.toBeNull();
    expect(saveButton(host).disabled).toBe(true);
});

test('an action inside a text box needs a modifier, so a bare letter is refused', () => {
    const verdict = judge(action('form.submit'), 'j', 'mac', ALL_ACTIONS, {});
    expect(verdict.refused).toBe('needs_modifier');
    expect(judge(action('palette.next'), 'y', 'other', ALL_ACTIONS, {}).refused).toBe('needs_modifier');
    expect(judge(action('terminal.search.next'), 'n', 'mac', ALL_ACTIONS, {}).refused).toBe('needs_modifier');
    expect(judge(action('form.submit'), 'cmd+j', 'mac', ALL_ACTIONS, {}).refused).toBeNull();
});

test('a saved change on a row the app does not read yet is ignored: its default is still live and still blocks', () => {
    const zoom = action('terminal.zoom.toggle');
    expect(zoom.rebindable).toBe(false);
    const chord = zoom.keys.mac[0]!;
    const stored = { mac: { [zoom.id]: ['cmd+9'] } };
    expect(judge(action('history.back'), chord, 'mac', ALL_ACTIONS, stored).clashes.map((a) => a.id)).toContain(zoom.id);
    expect(judge(action('history.back'), 'cmd+9', 'mac', ALL_ACTIONS, stored).clashes.map((a) => a.id)).not.toContain(zoom.id);
});

test('a chord the app would run before a menu or the terminal blocks the save while a live binding sits under it', () => {
    const holder = ALL_ACTIONS.find((a) => a.scope.startsWith('menu') && a.keys.mac.some((c) => c.includes('cmd')));
    if (!holder) return;
    expect(judge(action('history.back'), holder.keys.mac.find((c) => c.includes('cmd'))!, 'mac', ALL_ACTIONS, {}).clashes.map((a) => a.id)).toContain(holder.id);
});

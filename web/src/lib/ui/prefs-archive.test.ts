/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { uiPrefs } from './prefs.svelte';
import Probe from './PrefsArchive.fixture.svelte';

let handle: ReturnType<typeof mount> | null = null;
beforeEach(() => uiPrefs.resetForTests());
afterEach(() => {
    if (handle) void unmount(handle);
    handle = null;
    document.body.innerHTML = '';
    uiPrefs.resetForTests();
});

test('the first read of each archive flag may happen inside a derived', () => {
    handle = mount(Probe, { target: document.body });
    flushSync();
    expect(document.querySelector('[data-probe]')?.textContent).toBe('false/false');
});

test('choosing a flag repaints the reader', () => {
    handle = mount(Probe, { target: document.body });
    flushSync();
    uiPrefs.setArchivedProjectsVisible(true);
    flushSync();
    expect(document.querySelector('[data-probe]')?.textContent).toBe('false/true');
});

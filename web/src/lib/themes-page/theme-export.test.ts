/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import ThemeInspector from './ThemeInspector.svelte';
import { exportTheme } from './theme-export';
import { previewPalette } from './preview-palette';
import type { ThemeManifest } from '../../opscenter/api';

const MANIFEST = {
    id: 'dusk', name: 'Dusk', description: 'a test theme', author: null, version: '1.0', source: 'user',
    cssVars: { '--color-bg-page': '#101010', '--color-accent': '#ff8800' }, xterm: { background: '#000000' },
} as unknown as ThemeManifest;

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

async function inspector(props: Record<string, unknown>): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(ThemeInspector, {
        target,
        props: {
            manifest: MANIFEST, palette: previewPalette(MANIFEST), active: false, starred: false,
            onapply: () => {}, onstar: () => {}, ...props,
        } as never,
    });
    await tick();
    flushSync();
    return target;
}

describe('exportTheme', () => {
    test('is GET /themes/{id}/export, saved as <id>.theme.json', async () => {
        const calls: string[] = [];
        const saved: Array<[string, unknown]> = [];
        const fetcher = (async (path: string) => {
            calls.push(path);
            return { id: 'dusk' };
        }) as never;
        const file = await exportTheme('dusk', fetcher, (name, doc) => (saved.push([name, doc]), name));
        expect(calls).toEqual(['/themes/dusk/export']);
        expect(saved).toEqual([['dusk.theme.json', { id: 'dusk' }]]);
        expect(file).toBe('dusk.theme.json');
    });

    test('an id is encoded, never spliced into the path raw', async () => {
        const calls: string[] = [];
        const fetcher = (async (path: string) => (calls.push(path), {})) as never;
        await exportTheme('../x', fetcher, (name) => name);
        expect(calls).toEqual(['/themes/..%2Fx/export']);
    });

    test('a refusal saves nothing', async () => {
        const saved: string[] = [];
        const fetcher = (async () => Promise.reject(new Error('no theme named dusk'))) as never;
        await expect(exportTheme('dusk', fetcher, (name) => (saved.push(name), name))).rejects.toThrow('no theme named dusk');
        expect(saved).toEqual([]);
    });
});

describe('the inspector', () => {
    test('offers export and says a theme installs only through the catalog', async () => {
        let asked = 0;
        const root = await inspector({ onexport: () => (asked += 1) });
        (root.querySelector('[data-theme-export]') as HTMLButtonElement).click();
        expect(asked).toBe(1);
        expect(root.querySelector('[data-theme-install-note]')?.textContent).toContain('signed release');
    });

    test('without an export handler there is no export button, and the note stays', async () => {
        const root = await inspector({});
        expect(root.querySelector('[data-theme-export]')).toBeNull();
        expect(root.querySelector('[data-theme-install-note]')).not.toBeNull();
    });

    test('an export outcome is said, a refusal as an alert', async () => {
        const root = await inspector({ onexport: () => {}, exportNotice: { text: 'could not export: gone', error: true } });
        const line = root.querySelector('[data-theme-export-notice]') as HTMLElement;
        expect(line.textContent).toBe('could not export: gone');
        expect(line.getAttribute('role')).toBe('alert');
    });
});

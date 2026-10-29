/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { mount, unmount } from 'svelte';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
import ConsentScripts from './ConsentScripts.svelte';
import InstallSheet from './InstallSheet.svelte';
import { cardView } from './card';
import {
    CLIP_MARKER,
    MAX_PATH_CHARS,
    MAX_PREVIEW_FILES,
    MAX_SCRIPT_FILES,
    boundedList,
    boundedPath,
    clipChars,
} from './bounds';
import type { CatalogHost } from './catalog';
import type { InstallPreview, PreviewFile } from './types';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

/** Let every microtask and every timer shorter than `ms` settle. */
function settle(ms = 0): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

let painted: Record<string, unknown> | null = null;

afterEach(() => {
    if (painted) unmount(painted as never, { outro: false });
    painted = null;
    document.body.innerHTML = '';
});

function paint(component: unknown, props: Record<string, unknown>): void {
    const target = document.createElement('div');
    document.body.appendChild(target);
    painted = mount(component as never, { target, props } as never) as Record<string, unknown>;
}

describe('the pure bounds', () => {
    test('a string over the bound is clipped and says so', () => {
        const clipped = clipChars('A'.repeat(500), 10);
        expect(clipped).toHaveLength(10);
        expect(clipped?.endsWith(CLIP_MARKER)).toBe(true);
    });

    test('a string under the bound is returned untouched, marker and all', () => {
        expect(clipChars('scripts/run.sh', 120)).toBe('scripts/run.sh');
        expect(clipChars('scripts/run.sh', 120)?.includes(CLIP_MARKER)).toBe(false);
    });

    test('it clips by code point, so an astral character is never halved', () => {
        const clipped = clipChars('\u{1F600}'.repeat(40), 10);
        expect([...(clipped ?? '')]).toHaveLength(10);
        expect(clipped).not.toMatch(/[\uD800-\uDBFF](?![\uDC00-\uDFFF])/);
    });

    test('a path is clipped to the path bound', () => {
        const long = 'scripts/' + 'A'.repeat(50_000);
        expect([...boundedPath({ path: long })]).toHaveLength(MAX_PATH_CHARS);
        expect(boundedPath({ path: long }).endsWith(CLIP_MARKER)).toBe(true);
    });

    test('a short path comes through exactly as the server spelled it', () => {
        expect(boundedPath({ path: 'scripts/run.sh' })).toBe('scripts/run.sh');
    });

    test('a list over the cap is cut and the remainder is COUNTED, not dropped', () => {
        const files = Array.from({ length: 3000 }, (_, i) => ({ path: `f${i}` }));
        const bounded = boundedList(files, MAX_SCRIPT_FILES);
        expect(bounded.shown).toHaveLength(MAX_SCRIPT_FILES);
        expect(bounded.hidden).toBe(3000 - MAX_SCRIPT_FILES);
    });

    test('a list under the cap comes through whole with nothing hidden', () => {
        const files = [{ path: 'a' }, { path: 'b' }];
        const bounded = boundedList(files, MAX_SCRIPT_FILES);
        expect(bounded.shown).toHaveLength(2);
        expect(bounded.hidden).toBe(0);
    });
});

describe('the consent gate honours them', () => {
    function hostileScripts(count: number): PreviewFile[] {
        return Array.from({ length: count }, (_, i) => ({
            path: 'scripts/' + 'A'.repeat(50_000) + i,
            size: 1,
        }));
    }

    test('three thousand script files paint at most the cap', async () => {
        paint(ConsentScripts, {
            scripts: hostileScripts(3000),
            accepted: false,
            expressible: true,
            busy: false,
            t,
            onAccept: vi.fn(),
        });
        await settle();
        expect(document.querySelectorAll('.consent__file')).toHaveLength(MAX_SCRIPT_FILES);
        expect((document.querySelector('.consent__more')?.textContent ?? '').trim()).toBe(
            t(SKILL_KEYS.filesMore, { count: 3000 - MAX_SCRIPT_FILES }),
        );
    });

    test('and every path it paints is clipped to the path bound', async () => {
        paint(ConsentScripts, {
            scripts: hostileScripts(3),
            accepted: false,
            expressible: true,
            busy: false,
            t,
            onAccept: vi.fn(),
        });
        await settle();
        const first = (document.querySelector('.consent__file')?.textContent ?? '').trim();
        expect([...first]).toHaveLength(MAX_PATH_CHARS);
        expect(first.endsWith(CLIP_MARKER)).toBe(true);
    });

    test('a short list paints whole and prints no "more" line at all', async () => {
        paint(ConsentScripts, {
            scripts: [{ path: 'scripts/run.sh' }, { path: 'scripts/clean.sh' }],
            accepted: false,
            expressible: true,
            busy: false,
            t,
            onAccept: vi.fn(),
        });
        await settle();
        expect(document.querySelectorAll('.consent__file')).toHaveLength(2);
        expect(document.querySelector('.consent__more')).toBeNull();
        expect(document.querySelector('.consent__file')?.textContent?.trim()).toBe(
            'scripts/run.sh',
        );
    });
});

describe('the install sheet honours them', () => {
    const HOSTILE: InstallPreview = {
        body: '# a skill',
        files: Array.from({ length: 3000 }, (_, i) => ({
            path: 'docs/' + 'A'.repeat(50_000) + i,
            size: 1,
        })),
        publisher: 'P'.repeat(20_000),
        version: 'V'.repeat(20_000),
        digest: 'abc',
        digest_prefix: 'abc',
        body_sha: 'sha',
        index_host: 'H'.repeat(20_000),
        key_id: 'K'.repeat(20_000),
    };

    function previewHost(preview: InstallPreview): CatalogHost {
        const refuse = () => Promise.reject(new Error('the test never calls this'));
        return {
            listItems: refuse,
            refreshIndex: refuse,
            listInstalled: refuse,
            previewInstall: () => Promise.resolve(preview),
            install: () => Promise.resolve({ install_id: 'i1' }),
            uninstall: refuse,
            item: refuse,
            patchInstalled: refuse,
            applyUpdate: refuse,
            runningSessions: () => [],
            oneShot: refuse,
            listProjects: () => Promise.resolve([]),
            currentProjectPath: () => Promise.resolve(null),
        } as unknown as CatalogHost;
    }

    async function paintSheet(preview: InstallPreview): Promise<void> {
        paint(InstallSheet, {
            card: cardView({ id: 'a/b', name: 'x' }, false),
            host: previewHost(preview),
            t,
            close: vi.fn(),
        });
        await settle();
    }

    test('the file manifest paints at most the cap and counts the rest', async () => {
        await paintSheet(HOSTILE);
        expect(document.querySelectorAll('.sheet__file')).toHaveLength(MAX_PREVIEW_FILES);
        expect((document.querySelector('.sheet__more')?.textContent ?? '').trim()).toBe(
            t(SKILL_KEYS.filesMore, { count: 3000 - MAX_PREVIEW_FILES }),
        );
    });

    test('no fact on the sheet is longer than the bound written for it', async () => {
        await paintSheet(HOSTILE);
        const values = [...document.querySelectorAll('.sheet__facts dd')].map((node) =>
            (node.textContent ?? '').trim(),
        );
        expect(values.length).toBeGreaterThan(3);
        for (const value of values) {
            expect([...value].length).toBeLessThanOrEqual(MAX_PATH_CHARS);
        }
    });

    test('every path in the manifest is clipped too', async () => {
        await paintSheet(HOSTILE);
        const first = (
            document.querySelector('.sheet__file-path')?.textContent ?? ''
        ).trim();
        expect([...first]).toHaveLength(MAX_PATH_CHARS);
    });

    test('an ordinary preview is painted whole, with no cut and no count', async () => {
        // NEGATIVE CONTROL for
        await paintSheet({
            body: '# a skill',
            files: [{ path: 'SKILL.md', size: 10 }],
            publisher: 'alex',
            version: '1.0',
            digest: 'abc',
            digest_prefix: 'abc',
            body_sha: 'sha',
            index_host: 'skills.example',
            key_id: 'key-1',
        });
        expect(document.querySelectorAll('.sheet__file')).toHaveLength(1);
        expect(document.querySelector('.sheet__more')).toBeNull();
        expect(document.querySelector('.sheet__file-path')?.textContent?.trim()).toBe('SKILL.md');
        const values = [...document.querySelectorAll('.sheet__facts dd')].map((node) =>
            (node.textContent ?? '').trim(),
        );
        expect(values).toContain('alex');
        expect(values).toContain('skills.example');
    });
});

/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import CompatBadges from './CompatBadges.svelte';
import PacksShelf from './PacksShelf.svelte';
import TrustBlock from './TrustBlock.svelte';
import TrySheet from './TrySheet.svelte';
import { cardViews } from './card';
import { isPressable, isTyping, keyAction } from './keys';
import { catalogHashItem } from './screen-host';
import { isWarezHash } from './warez-host';
import { sortCards } from './sort';
import { previewText, tryPrompt } from './try-it';
import type { CatalogHost } from './catalog';
import type { CatalogItem, CatalogVersion } from './types';
import { createI18n } from '../../../../client/js/i18n/runtime.js';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const VERSION = {
    v: '1.0.0',
    digest: 'a'.repeat(64),
    scripts: 2,
    published_at: '2026-09-01T00:00:00Z',
    sig: { key_id: 'KEY123' },
    src: { repo: 'acme/skills', path: 'sme', commit: 'b'.repeat(40) },
    review: { status: 'reviewed', verdict: 'clean', warnings: [] },
} as unknown as CatalogVersion;

let mounted: Record<string, unknown> | null = null;
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

async function paint(component: never, props: Record<string, unknown>): Promise<void> {
    const target = document.createElement('div');
    document.body.appendChild(target);
    mounted = mount(component, { target, props: { t, ...props } as never }) as never;
    await flush();
}

afterEach(() => {
    if (mounted) unmount(mounted as never);
    mounted = null;
    document.body.innerHTML = '';
});

describe('trust block', () => {
    test('prints what the index carries and says so when it does not', async () => {
        await paint(TrustBlock as never, { version: VERSION });
        const text = document.body.textContent ?? '';
        expect(text).toContain('signed by');
        expect(text).toContain('pinned key');
        expect(text).toContain('aaaaaaaaaaaa');
        expect(text).toContain('acme/skills at bbbbbbbbbbbb');
        expect(text).toContain('2 scripts');
        unmount(mounted as never);
        document.body.innerHTML = '';
        await paint(TrustBlock as never, { version: null });
        const bare = document.body.textContent ?? '';
        expect(bare).toContain('names no signing key');
        expect(bare).toContain('no security review was published');
        expect(bare).not.toContain('digest');
        expect(bare).not.toContain('ships');
    });
});

describe('compat badges', () => {
    test('a harness shows only when the author names it', async () => {
        const item = {
            fm: { compatibility: 'works in Claude Code and codex', allowed_tools: ['Read', 'Bash'] },
        } as unknown as CatalogItem;
        await paint(CompatBadges as never, { item });
        const badges = [...document.querySelectorAll('.cat-compat__badge')].map((n) => n.textContent);
        expect(badges).toEqual(['claude', 'codex']);
        expect(document.body.textContent).toContain('allowed tools: Read, Bash');
        unmount(mounted as never);
        document.body.innerHTML = '';
        await paint(CompatBadges as never, { item: { fm: {} } });
        expect(document.querySelectorAll('.cat-compat__badge').length).toBe(0);
        expect(document.body.textContent).toContain('does not say');
    });
});

describe('try it', () => {
    const preview = { body: '---\nname: sme\n---\nbody text' };

    test('an installed item (409 name_taken) still yields its text; other refusals do not', async () => {
        const detail = { code: 'name_taken', ...preview };
        const taken = Object.assign(new Error('taken'), { detail, body: { detail } });
        const refused = Object.assign(new Error('nope'), { body: { code: 'key_untrusted' } });
        const hostWith = (error: unknown) =>
            ({ previewInstall: () => Promise.reject(error) }) as unknown as CatalogHost;
        expect(await previewText(hostWith(taken), 'a/b')).toBe(preview.body);
        const flat = Object.assign(new Error('taken'), { body: detail });
        expect(await previewText(hostWith(flat), 'a/b')).toBe(preview.body);
        await expect(previewText(hostWith(refused), 'a/b')).rejects.toBe(refused);
    });

    test('the prompt never starts with a dash, folds the task, and refuses an oversize body', () => {
        const built = tryPrompt(preview.body, 'do\nit', t);
        expect(built.prompt?.startsWith('-')).toBe(false);
        expect(built.prompt).toContain('task: do it');
        expect(tryPrompt('x'.repeat(9000), '', t)).toEqual({ prompt: null, tooLarge: true });
    });

    test('the sheet warns on many files, and starts the scratch session with the task', async () => {
        const sent: string[] = [];
        const host = {
            tryInScratch: async (prompt: string) => {
                sent.push(prompt);
                return {};
            },
        } as unknown as CatalogHost;
        await paint(TrySheet as never, {
            name: 'sme',
            body: preview.body,
            files: 3,
            host,
            close: () => {},
        });
        expect(document.body.textContent).toContain('this item has 3 files');
        const input = document.querySelector('.cat-try__input') as HTMLInputElement;
        input.value = 'review my repo';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await flush();
        const run = [...document.querySelectorAll('button')].find((b) =>
            b.textContent?.includes('start scratch session'),
        ) as HTMLButtonElement;
        run.click();
        await flush();
        expect(sent).toHaveLength(1);
        expect(sent[0]).toContain('task: review my repo');
        expect(document.body.textContent).toContain('scratch session is starting');
    });
});

describe('packs shelf and sort', () => {
    const items = [
        { id: 'a/pack', kind: 'loadout', name: 'pack', latest: '1', card: { title: 'zeta pack' }, versions: [{ ...VERSION, v: '1', published_at: '2026-01-01' }] },
        { id: 'a/skill', kind: 'skill', name: 'skill', latest: '1', card: { title: 'alpha' }, versions: [{ ...VERSION, v: '1', published_at: '2026-06-01' }] },
    ] as unknown as CatalogItem[];
    const cards = cardViews(items, false);

    test('only loadouts are on the shelf', async () => {
        await paint(PacksShelf as never, { cards, selectedId: null, onSelect: () => {} });
        const shelf = [...document.querySelectorAll('.cat-packs__name')].map((n) => n.textContent?.trim());
        expect(shelf).toEqual(['zeta pack']);
    });

    test('name and updated orders', () => {
        expect(sortCards(cards, 'name', items).map((c) => c.id)).toEqual(['a/skill', 'a/pack']);
        expect(sortCards(cards, 'updated', items).map((c) => c.id)).toEqual(['a/skill', 'a/pack']);
        expect(sortCards(cards, 'index', items).map((c) => c.id)).toEqual(['a/pack', 'a/skill']);
    });
});

describe('keyboard and deep links', () => {
    test('keys map, and never fire while typing or with a modifier', () => {
        expect(keyAction({ key: 'j' }, false)).toBe('next');
        expect(keyAction({ key: '/' }, false)).toBe('search');
        expect(keyAction({ key: '?' }, false)).toBe('help');
        expect(keyAction({ key: 'j' }, true)).toBeNull();
        expect(keyAction({ key: 'i', metaKey: true }, false)).toBeNull();
        expect(isTyping(document.createElement('input'))).toBe(true);
        expect(isTyping(document.createElement('button'))).toBe(false);
        expect(isPressable(document.createElement('button'))).toBe(true);
        expect(isPressable(document.createElement('div'))).toBe(false);
        const fold = document.createElement('details');
        const summary = document.createElement('summary');
        fold.appendChild(summary);
        expect(isPressable(summary)).toBe(true);
        expect(keyAction({ key: 'Enter' }, false, isPressable(summary))).toBeNull();
        expect(keyAction({ key: 'Enter' }, false, true)).toBeNull();
        expect(keyAction({ key: 'Enter' }, false, false)).toBe('open');
        expect(keyAction({ key: 'j' }, false, true)).toBe('next');
    });

    test('a warez or catalog hash names an item, and only those do', () => {
        expect(isWarezHash('#catalog')).toBe(true);
        expect(isWarezHash('#catalog/acme/sme')).toBe(true);
        expect(isWarezHash('#catalogue')).toBe(false);
        expect(catalogHashItem('#catalog/acme/sme')).toBe('acme/sme');
        expect(catalogHashItem('#warez/acme/sme')).toBe('acme/sme');
        expect(catalogHashItem('#catalog')).toBeNull();
        expect(catalogHashItem('#catalog/%E0%A4%A')).toBeNull();
    });
});

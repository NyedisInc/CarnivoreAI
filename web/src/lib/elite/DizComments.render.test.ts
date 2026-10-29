/** @vitest-environment jsdom */
import { unmountPanel } from '../mount';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { CatalogHost } from '../catalog/catalog';
import type { CatalogItem } from '../catalog/types';
import type { Comment, CommunityHost } from '../community/community';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const ITEMS: CatalogItem[] = [
    { id: 'acme/deploy', name: 'deploy', kind: 'skill', publisher: 'acme', latest: '1.0', card: { title: 'Deploy Runner' }, versions: [] },
    { id: 'zoe/dusk', name: 'dusk', kind: 'theme', publisher: 'zoe', latest: '1.0', card: { title: 'Dusk' }, versions: [] },
    { id: 'kim/lint', name: 'lint', kind: 'skill', publisher: 'kim', latest: '1.0', card: { title: 'Lint Rules' }, versions: [] },
] as unknown as CatalogItem[];

const EXISTING: Comment[] = [
    { id: 'c1', body: 'works great', author: { handle: 'zoe' } },
    { id: 'c2', body: 'needs a readme', author: { handle: 'kim' } },
] as unknown as Comment[];

function catalogHost(): CatalogHost {
    const refuse = () => Promise.reject(new Error('the test never calls this'));
    return {
        listItems: () => Promise.resolve({ index: { as_of: '2026-10-16' }, items: ITEMS, untrusted: [] }),
        refreshIndex: refuse,
        opened: () => Promise.resolve({}),
        listInstalled: () => Promise.resolve({ items: [] }),
        catalogSession: () => Promise.resolve({ signed_in: true, login: 'acme' }),
        itemInstalls: refuse,
        installCounts: refuse,
        itemRatings: refuse,
        listProjects: () => Promise.resolve([]),
        currentProjectPath: () => Promise.resolve(null),
    } as unknown as CatalogHost;
}

function communityHost(post: CommunityHost['post']): CommunityHost {
    return {
        comments: () => Promise.resolve({ comments: EXISTING, cursor: null }),
        post,
    } as unknown as CommunityHost;
}

const settle = (ms = 0): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

function press(code: string, key: string, init: KeyboardEventInit = {}, target: EventTarget = document.body): void {
    target.dispatchEvent(new KeyboardEvent('keydown', { code, key, bubbles: true, cancelable: true, ...init }));
}

const selected = (root: HTMLElement): string | null => root.querySelector('.fa-row[aria-selected="true"]')?.getAttribute('data-id') ?? null;
const rowsOf = (root: HTMLElement): string[] => Array.from(root.querySelectorAll('.dz-cm .dz-c')).map((li) => li.textContent ?? '');

let elite: HTMLElement;

async function openBoard(post: CommunityHost['post']): Promise<void> {
    const { ensurePanel: ensure } = await import('../mount');
    const EliteScreen = (await import('./EliteScreen.svelte')).default;
    ensure('elite-screen', EliteScreen as never, { host: catalogHost(), community: communityHost(post), t } as never);
    const { openEliteScreen } = await import('./elite-host');
    openEliteScreen({ direct: true });
    await settle(400);
}

beforeEach(() => {
    vi.stubGlobal('innerWidth', 1440);
    Element.prototype.scrollIntoView = vi.fn();
    vi.stubGlobal('AudioContext', class { state = 'suspended'; resume = () => Promise.resolve(); close = () => Promise.resolve(); });
    elite = document.createElement('div');
    elite.id = 'elite-screen';
    document.body.appendChild(elite);
});

afterEach(async () => {
    const { closeEliteScreen } = await import('./elite-host');
    closeEliteScreen();
    unmountPanel('elite-screen');
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
});

describe('Elite Access comment prompt', () => {
    test('shift+M opens the prompt, letters do not move the list, enter posts once and the comment heads the list', async () => {
        const fresh = { id: 'c3', body: 'ship it', author: { handle: 'acme' } } as unknown as Comment;
        const post = vi.fn(() => Promise.resolve({ comment: fresh }));
        await openBoard(post as never);
        const first = selected(elite);
        expect(first).toBe('acme/deploy');
        expect(rowsOf(elite)).toHaveLength(2);
        expect(elite.querySelector('.dz-cn')!.textContent).toBe('(2)');

        press('KeyM', 'M', { shiftKey: true });
        await settle();
        const input = elite.querySelector<HTMLInputElement>('#dz-ci')!;
        expect(input).not.toBeNull();
        expect(document.activeElement).toBe(input);
        expect(elite.querySelector('.dz-cadd label')!.textContent).toBe('comment>');

        for (const [code, key] of [['KeyJ', 'j'], ['KeyK', 'k'], ['KeyA', 'a'], ['KeyG', 'g']] as const) press(code, key, {}, input);
        input.value = 'ship it';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        expect(selected(elite)).toBe(first);
        expect(post).not.toHaveBeenCalled();

        press('Enter', 'Enter', {}, input);
        await settle(20);
        expect(post).toHaveBeenCalledTimes(1);
        expect(post).toHaveBeenCalledWith('acme/deploy', { body: 'ship it' });
        expect(rowsOf(elite)).toHaveLength(3);
        expect(rowsOf(elite)[0]).toContain('ship it');
        expect(elite.querySelector('.dz-cn')!.textContent).toBe('(3)');
        expect(elite.querySelector('#dz-ci')).toBeNull();
        expect(selected(elite)).toBe(first);
    });

    test('esc posts nothing and closes the prompt', async () => {
        const post = vi.fn(() => Promise.resolve({ comment: null }));
        await openBoard(post as never);
        press('KeyM', 'M', { shiftKey: true });
        await settle();
        const input = elite.querySelector<HTMLInputElement>('#dz-ci')!;
        input.value = 'never sent';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        press('Escape', 'Escape', {}, input);
        await settle(20);
        expect(post).not.toHaveBeenCalled();
        expect(elite.querySelector('#dz-ci')).toBeNull();
        expect(rowsOf(elite)).toHaveLength(2);
    });

    test('a 401 shows the sign in echo and leaves the list unchanged', async () => {
        const post = vi.fn(() => Promise.reject(Object.assign(new Error('unauthorized'), { status: 401 })));
        await openBoard(post as never);
        press('KeyM', 'M', { shiftKey: true });
        await settle();
        const input = elite.querySelector<HTMLInputElement>('#dz-ci')!;
        input.value = 'hello';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        press('Enter', 'Enter', {}, input);
        await settle(20);
        expect(post).toHaveBeenCalledTimes(1);
        expect(elite.querySelector('.fa-echo')!.textContent).toContain('sign in to comment');
        expect(rowsOf(elite)).toHaveLength(2);
        expect(elite.querySelector('.dz-cn')!.textContent).toBe('(2)');
    });
});

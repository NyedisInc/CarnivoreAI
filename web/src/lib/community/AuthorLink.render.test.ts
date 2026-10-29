/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import AuthorLink from './AuthorLink.svelte';
import type { CommunityHost } from './community';

const t = (key: string) => key;
let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

const host = { profile: () => new Promise(() => {}) } as unknown as CommunityHost;

function show(publisher: boolean) {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(AuthorLink, { target, props: { t, handle: 'ann', publisher, host } as never });
    return target;
}

describe('the author handle', () => {
    test('is a base Button with the publisher badge beside it', () => {
        const root = show(true);
        const button = root.querySelector('.alink__row > button')!;
        expect(button.getAttribute('data-btn')).toBe('quiet');
        expect(button.getAttribute('data-size')).toBe('sm');
        expect(button.textContent).toContain('ann');
        expect(root.querySelector('.alink__badge')?.textContent).toBe('community.badge.publisher');
    });

    test('no badge for a plain author, and a press opens then closes the page', async () => {
        const root = show(false);
        expect(root.querySelector('.alink__badge')).toBeNull();
        const button = root.querySelector<HTMLButtonElement>('.alink__row > button')!;
        expect(button.getAttribute('aria-expanded')).toBe('false');
        button.click();
        await tick();
        flushSync();
        expect(button.getAttribute('aria-expanded')).toBe('true');
        expect(root.querySelector('.alink--open')).not.toBeNull();
        button.click();
        await tick();
        flushSync();
        expect(root.querySelector('.alink--open')).toBeNull();
    });
});

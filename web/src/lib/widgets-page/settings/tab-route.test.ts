/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test } from 'vitest';
import { commitOnOpen, commitTab, hashForTab, tabFromLocation } from './tab-route';

describe('tabFromLocation', () => {
    test('#widgets/settings opens settings', () => expect(tabFromLocation('#widgets/settings', '')).toBe('settings'));
    test('?tab=settings counts only with #widgets', () => {
        expect(tabFromLocation('#widgets', '?tab=settings')).toBe('settings');
        expect(tabFromLocation('', '?tab=settings')).toBeNull();
    });
    test('#widgets alone names no tab', () => expect(tabFromLocation('#widgets', '')).toBeNull());
});

describe('commitTab', () => {
    beforeEach(() => window.history.replaceState(null, '', '/?tab=settings&x=1#widgets'));
    test('writes the hash and strips the applied ?tab= without a new history entry', () => {
        const before = window.history.length;
        commitTab('settings', window);
        expect(window.location.hash).toBe(hashForTab('settings'));
        expect(window.location.search).toBe('?x=1');
        expect(window.history.length).toBe(before);
    });
});

describe('opening the page from the menu', () => {
    test('Back returns to the previous view: opening writes nothing, so the shell\'s push is a new entry', async () => {
        const { pushPageHash } = await import('../../menu-page/menu-page-hash');
        const { menuPage } = await import('../../menu-page/menu-pages');
        window.history.replaceState(null, '', '/#home');
        window.history.pushState(null, '', '/#before');
        commitOnOpen('settings', window);
        expect(window.location.hash).toBe('#before');
        expect(pushPageHash(menuPage('widgets')!)).toBe(true);
        expect(window.location.hash).toBe('#widgets');
        const traversed = new Promise<void>((resolve) => window.addEventListener('popstate', () => resolve(), { once: true }));
        window.history.back();
        await traversed;
        expect(window.location.hash).toBe('#before');
    });
    test('a ?tab= link is still stripped', () => {
        window.history.replaceState(null, '', '/?tab=settings#widgets');
        commitOnOpen('settings', window);
        expect(window.location.search).toBe('');
        expect(window.location.hash).toBe('#widgets/settings');
    });
});

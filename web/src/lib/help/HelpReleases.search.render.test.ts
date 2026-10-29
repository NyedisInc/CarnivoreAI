/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

const payload = vi.hoisted(() => ({
    available: true,
    areas: [],
    catalog: [{ id: 'kc', name: 'Keychain', summary: 'reads the vault', area: 'a', status: 'shipped', how_to: ['open the vault panel'] }],
    changes: [
        { date: '2026-09-20', type: 'added', features: ['kc'], summary: 'reads the macOS keychain <b>x</b>', release: 'v1.2.0' },
        { date: '2026-09-19', type: 'fixed', features: [], summary: 'the update icon shifts when shift is held', release: 'v1.1.0' },
        { date: '2026-09-18', type: 'fixed', features: [], summary: 'nothing to see', release: 'v1.0.0' },
    ],
}));

vi.mock('../../opscenter/api/auth.svelte', () => ({ authFetch: async () => payload }));

import HelpReleases from './HelpReleases.svelte';

const tick = () => new Promise((r) => setTimeout(r, 0));

describe('changelog search render', () => {
    let target: HTMLElement;
    let component: unknown;
    afterEach(() => {
        if (component) unmount(component as never);
        target?.remove();
    });

    async function render(query: string, onClearQuery?: () => void, fuzzy = false): Promise<void> {
        target = document.body.appendChild(document.createElement('div'));
        component = mount(HelpReleases, { target, props: { query, onClearQuery, fuzzy } });
        await tick();
        flushSync();
    }

    const names = () => [...target.querySelectorAll('.sidebar-help__release-name')].map((e) => e.textContent?.trim());

    it('with no query every release shows, in order', async () => {
        await render('');
        expect(names()).toEqual(['v1.2.0', 'v1.1.0', 'v1.0.0']);
        expect(target.querySelector('[data-changelog-count]')).toBeNull();
    });

    it('a typo query finds nothing while the fuzzy box is off', async () => {
        await render('keychan');
        expect(names()).toEqual([]);
    });

    it('a typo query keeps only the release with a hit, highlighted, with a count, with fuzzy on', async () => {
        await render('keychan', undefined, true);
        expect(names()).toEqual(['v1.2.0']);
        const mark = target.querySelector('.sidebar-help__change-summary mark');
        expect(mark?.textContent).toBe('keychain');
        expect(target.querySelector('[data-changelog-count]')?.textContent).toContain('1 match');
    });

    it('an untrusted <b> in a summary stays text, never an element', async () => {
        await render('keychain');
        expect(target.querySelector('.sidebar-help__change-summary b')).toBeNull();
        expect(target.querySelector('.sidebar-help__change-summary')?.textContent).toContain('<b>x</b>');
    });

    it('word order does not matter and the matching release is forced open', async () => {
        await render('shift update', undefined, true);
        expect(names()).toEqual(['v1.1.0']);
        expect(target.querySelectorAll('.sidebar-help__change-row').length).toBe(1);
    });

    it('a body-only hit opens its row', async () => {
        await render('vault');
        expect(target.querySelector('.sidebar-help__change-detail')).not.toBeNull();
    });

    it('no match shows the empty sentence and the clear button calls back', async () => {
        const clear = vi.fn();
        await render('zzzzzz', clear);
        expect(names()).toEqual([]);
        expect(target.querySelector('[data-changelog-count]')?.textContent).toContain('no changes match');
        (target.querySelector('[data-changelog-clear]') as HTMLButtonElement).click();
        expect(clear).toHaveBeenCalledOnce();
    });
});

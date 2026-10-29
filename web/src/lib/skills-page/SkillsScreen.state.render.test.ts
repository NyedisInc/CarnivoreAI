/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../../opscenter/api/events.svelte', () => ({ subscribe: () => () => {} }));

import SkillsScreen from './SkillsScreen.svelte';
import { fakeServer } from './skills-fixtures';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { Translate } from '../sessions/types';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

async function settle(): Promise<void> {
    for (let round = 0; round < 4; round += 1) {
        for (let i = 0; i < 8; i += 1) await Promise.resolve();
        await tick();
        flushSync();
    }
}

async function page(): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(SkillsScreen, { target, props: { embedded: true, fetcher: fakeServer().fetcher, t } });
    await settle();
    return target;
}

const card = (root: HTMLElement, name: string): HTMLElement => root.querySelector<HTMLElement>(`[data-item-id="${name}"]`) as HTMLElement;

async function open(root: HTMLElement, name: string): Promise<void> {
    (card(root, name).querySelector('.catalog-card__open') as HTMLElement).click();
    await settle();
}

describe('the full state of a skill', () => {
    test('a drifted, flagged, used catalog skill shows every section', async () => {
        const root = await page();
        await open(root, 'sme');
        const sections = [...root.querySelectorAll('[data-skill-section]')].map((s) => s.getAttribute('data-skill-section'));
        expect(sections).toEqual(['usage', 'health', 'provenance', 'contents']);
        const usage = root.querySelector('[data-skill-section="usage"]')!.textContent!;
        expect(usage).toContain('fired 4 times in 30 days');
        expect(usage).toContain('fired 1 time in 7 days');
        expect(usage).toContain('fired 9 times in 90 days');
        const health = root.querySelector('[data-skill-section="health"]')!;
        expect(health.querySelector('[data-drift="drifted"]')).not.toBeNull();
        expect(health.textContent).toContain('SKILL.md');
        expect(health.querySelector('[data-tripwire="flagged"]')!.textContent).toContain('network');
        expect(health.textContent).toContain('tool calls');
        expect(health.querySelector('[data-skill-restore]')).not.toBeNull();
        expect(health.querySelector('[data-skill-fork]')).not.toBeNull();
        const prov = root.querySelector('[data-skill-section="provenance"]')!.textContent!;
        expect(prov).toContain('1.2.0');
        expect(prov).toContain('one click, no sheet');
        expect(prov).toContain('ADOOMKEY01');
        expect(prov).toContain('abcdef01');
        expect(root.querySelector('[data-skill-section="contents"] [data-skill-md-toggle]')).not.toBeNull();
    });

    test('a local skill with no usage says not measured, never zero, and has no install record', async () => {
        const root = await page();
        await open(root, 'progress');
        expect(root.querySelector('[data-skill-section="usage"]')!.textContent).toContain('not measured');
        expect(root.querySelector('[data-skill-section="usage"]')!.textContent).not.toMatch(/fired 0/);
        expect(root.querySelector('[data-skill-no-drift]')).not.toBeNull();
        expect(root.querySelector('[data-tripwire="not_judged"]')).not.toBeNull();
        expect(root.querySelector('[data-skill-local]')).not.toBeNull();
    });

    test('the list marks drifted, flagged and unused 30 d without opening a skill', async () => {
        const root = await page();
        const chips = (name: string): string =>
            Array.from(card(root, name).querySelectorAll('.mgr-chip')).map((c) => c.getAttribute('aria-label')).join(' | ');
        expect(chips('sme')).toContain('files changed since install');
        expect(chips('sme')).toContain('flagged by tripwire');
        expect(chips('noisy')).toContain('not used in the last 30 days');
        expect(chips('progress')).not.toContain('not used');
        expect(chips('progress')).not.toContain('files changed');
    });
});

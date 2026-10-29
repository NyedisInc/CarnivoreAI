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
    for (let i = 0; i < 4; i += 1) {
        for (let j = 0; j < 6; j += 1) await Promise.resolve();
        await tick();
        flushSync();
    }
}

async function open(tab: string): Promise<{ root: HTMLElement; server: ReturnType<typeof fakeServer> }> {
    const server = fakeServer();
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(SkillsScreen, { target, props: { embedded: true, fetcher: server.fetcher, t } });
    await settle();
    (target.querySelector(`[data-skills-tab="${tab}"]`) as HTMLElement).click();
    await settle();
    return { root: target, server };
}

const rowNames = (root: HTMLElement): string[] =>
    Array.from(root.querySelectorAll('.oc-rank__row')).map((r) => r.querySelector('.oc-rank__name')!.textContent!);

describe('census tab', () => {
    test('ranks skills by 30 day fires in DOM order (column-major), a null count says not measured and ranks last', async () => {
        const { root, server } = await open('census');
        expect(server.seen.some((s) => s.path.startsWith('/skills/census'))).toBe(true);
        expect(root.querySelectorAll('.oc-rank')).toHaveLength(1);
        expect(rowNames(root)).toEqual(['sme', 'noisy', 'blind']);
        expect(Array.from(root.querySelectorAll('.oc-rank__num')).map((n) => n.textContent)).toEqual(['1', '2', '3']);
        const metric = (name: string): string =>
            Array.from(root.querySelectorAll('.oc-rank__row')).find((r) => r.querySelector('.oc-rank__name')!.textContent === name)!
                .querySelector('.oc-rank__metric')!.textContent!.trim();
        expect(metric('sme')).toBe('4fires');
        expect(metric('noisy')).toBe('0fires');
        expect(metric('blind')).toBe('not measured');
        expect(root.querySelector('.oc-rank__head select[data-facet="skills-context"]')).not.toBeNull();
        expect(root.querySelector('.oc-rank.oc-rank--split')).not.toBeNull();
        expect(root.textContent).toContain('est. 150 tokens');
    });
});

/** @vitest-environment jsdom */
import { flushSync, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, test } from 'vitest';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { ApiError } from '../../opscenter/api/auth.svelte';
import LaunchStory from './LaunchStory.svelte';
import type { StoryApi, WorkItemList } from './story-model';

const i18n = createI18n({ locale: 'en' }) as { t(k: string, p?: Record<string, unknown> | null): string };
const t = (k: string, p?: Record<string, unknown> | null): string => i18n.t(k, p);

const ITEMS: WorkItemList = { enabled: true, state: 'ok', items: [
    { id: 'wi_feat1', kind: 'feature', parent_id: 'wi_proj1', title: 'Fixture Feature', sprint_state: 'active', updated_at: '2026-11-05' },
    { id: 'wi_story1', kind: 'story', parent_id: 'wi_feat1', title: 'Fixture Story', sprint_state: 'none', updated_at: '2026-11-04' },
] };

let host: HTMLElement | null = null;
let handle: ReturnType<typeof mount> | null = null;
afterEach(() => { if (handle) unmount(handle); handle = null; host?.remove(); host = null; });

async function draw(list: WorkItemList, create?: StoryApi['create']): Promise<{ answers: (string | null)[] }> {
    const answers: (string | null)[] = [];
    host = document.createElement('div');
    document.body.append(host);
    const state: { answer: string | null } = { answer: null };
    const api: StoryApi = { list: async () => list, create: create ?? (async () => { throw new Error('unused'); }) };
    handle = mount(LaunchStory, { target: host, props: { t, api, pollMs: 3600000, get answer() { return state.answer; }, set answer(v: string | null) { state.answer = v; answers.push(v); } } });
    await tick(); await tick(); flushSync();
    return { answers };
}

describe('the launch picker story row', () => {
    test('off draws nothing, so the picker is unchanged', async () => {
        await draw({ enabled: false, state: 'off', items: [] });
        expect(host!.querySelector('[data-launch-story]')).toBeNull();
    });

    test('on lists skip first then the grouped items, and a pick answers its id', async () => {
        const { answers } = await draw(ITEMS);
        const select = host!.querySelector<HTMLSelectElement>('[data-lst-pick]')!;
        expect([...select.options].map((o) => o.value)).toEqual(['', 'wi_feat1', 'wi_story1']);
        expect([...select.querySelectorAll('optgroup')].map((g) => g.label)).toEqual(['active sprint', 'recent']);
        select.value = 'wi_story1';
        select.dispatchEvent(new Event('change', { bubbles: true }));
        await tick(); flushSync();
        expect(answers.at(-1)).toBe('wi_story1');
        select.value = '';
        select.dispatchEvent(new Event('change', { bubbles: true }));
        await tick(); flushSync();
        expect(answers.at(-1)).toBeNull();
    });

    test('nothing cached says not available yet and skip still answers null', async () => {
        const { answers } = await draw({ enabled: true, state: 'unavailable', items: [] });
        expect(host!.querySelector('[data-lst-unavailable]')!.textContent).toBe('not available yet');
        expect(answers.at(-1) ?? null).toBeNull();
    });

    test('a 409 on create lists the candidates and joining one answers its id', async () => {
        const body = { detail: { code: 'conflict', details: { candidates: [{ id: 'wi_feat9', title: 'Login Rework', kind: 'feature' }] } } };
        const { answers } = await draw(ITEMS, async () => { throw new ApiError('conflict', 409, 'conflict', body); });
        host!.querySelector<HTMLButtonElement>('[data-lst-new]')!.click();
        await tick(); flushSync();
        const title = host!.querySelector<HTMLInputElement>('[data-lst-title]')!;
        title.value = 'login rework';
        title.dispatchEvent(new Event('input', { bubbles: true }));
        const kind = host!.querySelector<HTMLSelectElement>('[data-lst-kind]')!;
        kind.value = 'project';
        kind.dispatchEvent(new Event('change', { bubbles: true }));
        await tick(); flushSync();
        host!.querySelector<HTMLButtonElement>('[data-lst-create]')!.click();
        await tick(); await tick(); flushSync();
        const join = host!.querySelector<HTMLButtonElement>('[data-lst-join="wi_feat9"]')!;
        expect(join).not.toBeNull();
        join.click();
        await tick(); flushSync();
        expect(answers.at(-1)).toBe('wi_feat9');
    });
});

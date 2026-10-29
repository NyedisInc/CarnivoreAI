/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import RouteRow from './RouteRow.svelte';
import { setLocale } from '../i18n/index.svelte';
import type { Connection, ModelInfo, Preset, TargetRef } from './api';
import { ai } from './store.svelte';
import { panelWidth } from './picker-logic';

setLocale('en');

const PRESET: Preset = {
    id: 'openrouter', label: 'openrouter', kind: 'cloud', capabilities: { chat: ['openai_chat'] }, base_url: 'https://openrouter.ai/api/v1', auth: 'bearer',
    key_required: true, auth_choices: [], fields: [], docs_url: '', default_models: [], model_source: 'discover', custom: false,
};
const CONNECTION: Connection = {
    id: 'openrouter-1', preset: 'openrouter', label: 'openrouter', base_url: PRESET.base_url, options: {}, enabled: true, key_host: null, key_hint: '', has_key: true, models: {},
};
const model = (id: string, extra: Partial<ModelInfo> = {}): ModelInfo => ({ id, capabilities: ['chat'], flags: [], label: '', meta: {}, ...extra });
const VENDORS = ['anthropic', 'openai', 'google', 'meta', 'mistral', 'qwen'];
const MODELS: ModelInfo[] = [
    ...VENDORS.flatMap((v) => [model(`${v}/alpha`), model(`${v}/beta`)]).slice(0, 8),
    model('anthropic/claude-sonnet-5', { label: 'Claude Sonnet 5', meta: { popular_rank: 0 } }),
    model('openai/gpt-top', { meta: { popular_rank: 1 } }),
    model('meta/llama-used', {}),
    model('qwen/saved-one', {}),
];

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
    for (const m of mounted.splice(0)) await unmount(m);
    document.body.replaceChildren();
});

function render(saved: string | null = 'qwen/saved-one') {
    ai.presets = [PRESET];
    ai.config = { revision: 1, connections: [CONNECTION], defaults: {}, features: {} };
    ai.models = { 'openrouter-1': MODELS };
    ai.recent = { 'openrouter-1': [{ model: 'meta/llama-used', capability: 'chat' }, { model: 'typed/not-listed', capability: 'chat' }] };
    const set: TargetRef[] = [];
    const target: TargetRef | null = saved ? { connection: 'openrouter-1', model: saved, voice: null } : null;
    mounted.push(mount(RouteRow, { target: document.body, props: { name: 'chat', capability: 'chat', target, onSet: (t: TargetRef) => set.push(t), onClear: () => {} } }));
    flushSync();
    const field = document.body.querySelector<HTMLInputElement>('[data-ai="route-model-input"]')!;
    const key = (k: string) => { field.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true })); flushSync(); };
    const type = (text: string) => { field.value = text; field.dispatchEvent(new Event('input', { bubbles: true })); flushSync(); };
    const open = async () => { field.focus(); flushSync(); await Promise.resolve(); flushSync(); };
    const ids = () => [...document.body.querySelectorAll<HTMLElement>('[data-ai="route-model-option"]')].map((o) => o.dataset['id']);
    const heads = () => [...document.body.querySelectorAll('.ai-pick__head')].map((h) => h.textContent);
    return { set, field, key, type, open, ids, heads };
}

describe('the model picker', () => {
    test('opening with a model already set lists every model (the regression for "only 1")', async () => {
        const ui = render('qwen/saved-one');
        await ui.open();
        const list = document.body.querySelector('[data-ai="route-model-list"]')!;
        expect(list.getAttribute('data-count')).toBe(String(MODELS.length + 1));
        ui.key('End');
        expect(ui.ids()).toContain('qwen/saved-one');
        expect(document.body.querySelector('.ai-pick__opt--current')?.getAttribute('data-id')).toBe('qwen/saved-one');
        expect(ui.field.getAttribute('aria-expanded')).toBe('true');
        expect(document.body.querySelector('datalist')).toBeNull();
    });

    test('typing narrows the list, every word must match, and the match is highlighted', async () => {
        const ui = render();
        await ui.open();
        ui.type('claude son');
        expect(ui.ids()).toEqual(['anthropic/claude-sonnet-5']);
        expect(document.body.querySelector('.ai-pick__hit')?.textContent?.toLowerCase()).toContain('claude');
    });

    test('recent sits above popular, which sits above all', async () => {
        const ui = render();
        await ui.open();
        expect(ui.heads().slice(0, 2)).toEqual(['recent', 'popular']);
        const ids = ui.ids();
        expect(ids.slice(0, 2)).toEqual(['meta/llama-used', 'typed/not-listed']);
        expect(ids.slice(2, 4)).toEqual(['anthropic/claude-sonnet-5', 'openai/gpt-top']);
    });

    test('the keyboard picks a model and Set sends it', async () => {
        const ui = render('qwen/saved-one');
        await ui.open();
        ui.type('gpt');
        ui.key('ArrowDown');
        ui.key('ArrowUp');
        ui.key('Enter');
        expect(ui.field.getAttribute('aria-expanded')).toBe('false');
        expect(ui.field.value).toBe('openai/gpt-top');
        document.body.querySelector<HTMLButtonElement>('[data-ai="route-set"]')!.click();
        expect(ui.set).toEqual([{ connection: 'openrouter-1', model: 'openai/gpt-top', voice: null }]);
    });

    test("a typed id that nothing matches exactly offers use '<id>'", () => {
        const ui = render();
        ui.open();
        ui.type('us.anthropic.custom-v1');
        expect(document.body.querySelector('[data-ai="route-model-custom"]')?.textContent).toContain("use 'us.anthropic.custom-v1'");
        ui.key('Enter');
        expect(ui.field.value).toBe('us.anthropic.custom-v1');
        ui.key('Escape');
        expect(ui.field.getAttribute('aria-expanded')).toBe('false');
    });
});

describe('panelWidth', () => {
    const item = (text: string, detail: string) => ({ id: text, text, name: '', vendor: '', detail, flags: [] as string[] });
    test('grows past the field for long rows, stays capped and on screen', () => {
        const long = item('anthropic/claude-haiku-4.5-20251001', '200k ctx · $1 in, $5 out per million tokens');
        expect(panelWidth(300, [item('a/b', '')], 1280)).toBe(360);
        expect(panelWidth(300, [long], 1280)).toBeGreaterThan(360);
        expect(panelWidth(300, [item('x'.repeat(400), '')], 1280)).toBe(768);
        expect(panelWidth(300, [long], 400)).toBe(384);
    });
});

/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import SettingsForm from './SettingsForm.svelte';
import { createItemSettingsController } from './item-settings-controller.svelte';
import { memoryFetcher } from './memory-fetcher';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { fits, resolveValue, type Fetcher, type ItemSettingsPayload, type SettingValue } from './api';
import type { WidgetSettingsSchema } from '../../opscenter/widgets/types';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { PSEUDO_LOCALE } from '../../../../client/js/i18n/pseudo.js';
import type { Translate } from '../sessions/types';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);
const pseudo = createI18n({ locale: PSEUDO_LOCALE }) as { t: Translate };
const tPseudo: Translate = (key, params) => pseudo.t(key, params);

const SCHEMA = {
    version: 1,
    fields: {
        showSystem: { kind: 'boolean', labelKey: 'widgets.setting.activity_log.show_system', default: true },
        rows: { kind: 'number', labelKey: 'item_settings.specimen.rows', default: 8, min: 1, max: 50 },
        order: { kind: 'enum', labelKey: 'item_settings.specimen.order', default: 'newest', options: ['newest', 'oldest'], control: 'select' },
        caption: { kind: 'string', labelKey: 'item_settings.specimen.caption', default: '', maxLength: 40 },
    },
} as const satisfies WidgetSettingsSchema;

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 4; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

function form(values: Record<string, SettingValue>, extra: Record<string, unknown> = {}): {
    root: HTMLElement;
    changes: Array<[string, SettingValue | null]>;
} {
    const changes: Array<[string, SettingValue | null]> = [];
    const root = document.createElement('div');
    root.className = 'pledger mgr mgr--embedded';
    document.body.append(root);
    mounted = mount(SettingsForm, {
        target: root,
        props: { schema: SCHEMA, values, t, onChange: (key: string, value: SettingValue | null) => changes.push([key, value]), ...extra },
    });
    flushSync();
    return { root, changes };
}

const row = (root: HTMLElement, key: string): HTMLElement => root.querySelector(`[data-setting="${key}"]`)!;

describe('the form draws every kind from the schema', () => {
    test('one row per field, each with its label and the right control', () => {
        const { root } = form({});
        expect(root.querySelectorAll('.sf__row').length).toBe(4);
        expect(row(root, 'showSystem').querySelector('[role="switch"]')?.getAttribute('aria-checked')).toBe('true');
        const number = row(root, 'rows').querySelector<HTMLInputElement>('input[type="number"]')!;
        expect([number.value, number.min, number.max]).toEqual(['8', '1', '50']);
        const select = row(root, 'order').querySelector<HTMLSelectElement>('select')!;
        expect(Array.from(select.options).map((o) => o.textContent)).toEqual(['newest first', 'oldest first']);
        expect(select.value).toBe('newest');
        const text = row(root, 'caption').querySelector<HTMLInputElement>('input[type="text"]')!;
        expect(text.maxLength).toBe(40);
        expect(row(root, 'rows').querySelector('.sf__hint')?.textContent).toBe('from 1 to 50');
    });

    test('an untouched field says default; a stored one shows its value and offers use default', () => {
        const { root } = form({ rows: 12 });
        expect(row(root, 'rows').dataset.chosen).toBe('1');
        expect(row(root, 'rows').querySelector<HTMLInputElement>('input')!.value).toBe('12');
        expect(row(root, 'rows').querySelector('[data-sf-reset]')?.textContent?.trim()).toBe('use default');
        expect(row(root, 'caption').dataset.chosen).toBe('0');
        expect(row(root, 'caption').querySelector('.sf__default')?.textContent).toBe('default');
    });

    test('each control reports its own key and value; use default reports null', () => {
        const { root, changes } = form({ rows: 12 });
        row(root, 'showSystem').querySelector<HTMLButtonElement>('[role="switch"]')!.click();
        const number = row(root, 'rows').querySelector<HTMLInputElement>('input')!;
        number.value = '30';
        number.dispatchEvent(new Event('change', { bubbles: true }));
        const select = row(root, 'order').querySelector<HTMLSelectElement>('select')!;
        select.value = 'oldest';
        select.dispatchEvent(new Event('change', { bubbles: true }));
        const text = row(root, 'caption').querySelector<HTMLInputElement>('input')!;
        text.value = 'mine';
        text.dispatchEvent(new Event('change', { bubbles: true }));
        row(root, 'rows').querySelector<HTMLButtonElement>('[data-sf-reset]')!.click();
        expect(changes).toEqual([['showSystem', false], ['rows', 30], ['order', 'oldest'], ['caption', 'mine'], ['rows', null]]);
    });

    test('a number field that does not parse is sent as text, for the server to refuse', () => {
        const { root, changes } = form({});
        const number = row(root, 'rows').querySelector<HTMLInputElement>('input')!;
        Object.defineProperty(number, 'valueAsNumber', { value: Number.NaN });
        number.dispatchEvent(new Event('change', { bubbles: true }));
        expect(typeof changes[0]?.[1]).toBe('string');
    });

    test('while saving every control is disabled and the error sits under its own field', () => {
        const { root } = form({}, { busyKey: 'rows', error: { key: 'caption', text: 'too long' } });
        expect(Array.from(root.querySelectorAll<HTMLInputElement | HTMLButtonElement>('input, select, button')).every((el) => el.disabled)).toBe(true);
        expect(row(root, 'caption').querySelector('.sf__error')?.textContent).toBe('too long');
        expect(row(root, 'rows').querySelector('.sf__error')).toBeNull();
    });

    test('every word comes from the catalog', () => {
        const changes: unknown[] = [];
        const root = document.createElement('div');
        document.body.append(root);
        mounted = mount(SettingsForm, { target: root, props: { schema: SCHEMA, values: {}, t: tPseudo, onChange: () => changes.push(1) } });
        flushSync();
        expect(root.querySelector('.sf__title')?.textContent).toBe(tPseudo('item_settings.title'));
        expect(row(root, 'showSystem').querySelector('.sf__label')?.textContent).toBe(tPseudo('widgets.setting.activity_log.show_system'));
        expect(row(root, 'caption').querySelector('.sf__default')?.textContent).toBe(tPseudo('item_settings.default'));
    });
});

describe('resolveValue and fits', () => {
    test('a stored value is used only when it still fits; otherwise the default', () => {
        const rows = SCHEMA.fields.rows;
        expect(resolveValue(rows, 20)).toBe(20);
        expect(resolveValue(rows, 99)).toBe(8);
        expect(resolveValue(rows, undefined)).toBe(8);
        expect(fits(SCHEMA.fields.order, 'sideways')).toBe(false);
        expect(fits(SCHEMA.fields.caption, 'x'.repeat(41))).toBe(false);
        expect(fits(SCHEMA.fields.showSystem, 'true')).toBe(false);
    });
});

describe('the controller: the save path', () => {
    const id = 'specimen.every-kind';

    test('loads, then a change is one PATCH with the read revision, and the form shows the answer', async () => {
        const memory = memoryFetcher({ [id]: SCHEMA });
        const sent: unknown[] = [];
        const fetcher = (async (path: string, init?: RequestInit) => {
            if (init?.method === 'PATCH') sent.push(JSON.parse(String(init.body)));
            return memory(path, init);
        }) as Fetcher;
        let saved = 0;
        const ctl = createItemSettingsController('widget', id, t, fetcher, async () => { saved += 1; });
        await ctl.load();
        expect(ctl.status).toBe('ready');
        expect(ctl.item?.values).toEqual({});
        await ctl.change('rows', 20);
        expect(sent).toEqual([{ values: { rows: 20 }, expected_revision: 0 }]);
        expect(ctl.item?.values).toEqual({ rows: 20 });
        expect(ctl.item?.revision).toBe(1);
        expect(saved).toBe(1);
        await ctl.change('rows', null);
        expect(sent[1]).toEqual({ values: { rows: null }, expected_revision: 1 });
        expect(ctl.item?.values).toEqual({});
    });

    test('a refusal keeps the stored value and names the reason with the field bounds', async () => {
        const stored: ItemSettingsPayload = {
            kind: 'widget', id, enabled: null, switchable: true, values: { rows: 5 }, dropped: [], schema: SCHEMA, revision: 3,
        };
        const fetcher = (async (_path: string, init?: RequestInit) => {
            if (init?.method !== 'PATCH') return stored;
            throw new ApiError('rows: setting_above_max', 400, null, {
                detail: { code: 'setting_above_max', detail: 'rows: setting_above_max', key: 'rows' },
            });
        }) as Fetcher;
        const ctl = createItemSettingsController('widget', id, t, fetcher, async () => {});
        await ctl.load();
        await ctl.change('rows', 99);
        expect(ctl.item?.values).toEqual({ rows: 5 });
        expect(ctl.fieldError).toEqual({ key: 'rows', text: 'the highest allowed is 50' });
        expect(ctl.busyKey).toBeNull();
    });

    test('a 409 adopts the item another device wrote and does not replay the change', async () => {
        let patches = 0;
        const theirs: ItemSettingsPayload = {
            kind: 'widget', id, enabled: null, switchable: true, values: { order: 'oldest' }, dropped: [], schema: SCHEMA, revision: 7,
        };
        const fetcher = (async (_path: string, init?: RequestInit) => {
            if (init?.method !== 'PATCH') return { ...theirs, values: {}, revision: 2 };
            patches += 1;
            throw new ApiError('stale', 409, null, { detail: { code: 'item_settings_stale', detail: 'stale', current: theirs } });
        }) as Fetcher;
        const ctl = createItemSettingsController('widget', id, t, fetcher, async () => {});
        await ctl.load();
        await ctl.change('order', 'newest');
        expect(patches).toBe(1);
        expect(ctl.item).toEqual(theirs);
        expect(ctl.notice).toBe(t('item_settings.notice.stale'));
        expect(ctl.fieldError).toBeNull();
    });

    test('a failed load is an error state in words, not an empty form', async () => {
        const fetcher = (async () => { throw new ApiError('the server said no', 503); }) as Fetcher;
        const ctl = createItemSettingsController('widget', id, t, fetcher, async () => {});
        await ctl.load();
        expect(ctl.status).toBe('error');
        expect(ctl.loadError).toBe('the server said no');
        expect(ctl.item).toBeNull();
    });
});

describe('the panel over the controller', () => {
    test('renders the form for the schema the server answered, and nothing for an item with none', async () => {
        const { default: ItemSettingsPanel } = await import('./ItemSettingsPanel.svelte');
        const root = document.createElement('div');
        root.className = 'pledger mgr mgr--embedded';
        document.body.append(root);
        const ctl = createItemSettingsController('widget', 'x.none', t, memoryFetcher({ 'x.none': null }), async () => {});
        mounted = mount(ItemSettingsPanel, { target: root, props: { kind: 'widget', id: 'x.none', t, controller: ctl } });
        await settle();
        expect(ctl.status).toBe('ready');
        expect(root.querySelector('[data-settings-form]')).toBeNull();
        unmount(mounted);
        const withFields = createItemSettingsController('widget', 'x.some', t, memoryFetcher({ 'x.some': SCHEMA }), async () => {});
        mounted = mount(ItemSettingsPanel, { target: root, props: { kind: 'widget', id: 'x.some', t, controller: withFields } });
        await settle();
        expect(root.querySelectorAll('.sf__row').length).toBe(4);
    });
});

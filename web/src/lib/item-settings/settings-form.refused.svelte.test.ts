/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import SettingsForm from './SettingsForm.svelte';
import type { WidgetSettingsSchema } from '../../opscenter/widgets/types';
import type { SettingValue } from './api';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { Translate } from '../sessions/types';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

const SCHEMA = {
    version: 1,
    fields: {
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

function type(el: HTMLInputElement | HTMLSelectElement, value: string): void {
    el.value = value;
    el.dispatchEvent(new Event('change', { bubbles: true }));
}

test('a refused number, text and select change puts the stored value back', async () => {
    const props = $state<{ schema: typeof SCHEMA; values: Record<string, SettingValue>; t: Translate; onChange: () => void; error: { key: string; text: string } | null }>({
        schema: SCHEMA, values: { rows: 12, caption: 'hello', order: 'oldest' }, t, onChange: () => {}, error: null,
    });
    const root = document.createElement('div');
    document.body.append(root);
    mounted = mount(SettingsForm, { target: root, props });
    flushSync();
    const rows = root.querySelector<HTMLInputElement>('[data-setting="rows"] input')!;
    const caption = root.querySelector<HTMLInputElement>('[data-setting="caption"] input')!;
    const order = root.querySelector<HTMLSelectElement>('[data-setting="order"] select')!;
    type(rows, '99');
    type(caption, 'refused words');
    type(order, 'newest');

    props.error = { key: 'rows', text: 'too many' };
    await tick();
    flushSync();
    expect(rows.value).toBe('12');
    props.error = { key: 'caption', text: 'no' };
    await tick();
    flushSync();
    expect(caption.value).toBe('hello');
    props.error = { key: 'order', text: 'no' };
    await tick();
    flushSync();
    expect(order.value).toBe('oldest');
});

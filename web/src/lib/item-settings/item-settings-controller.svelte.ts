/* no longer holds */
import { t as appT } from '../i18n/index.svelte';
import type { Translate } from '../sessions/types';
import { itemSettings } from './store.svelte';
import {
  readItem,
  refusalOf,
  writeItem,
  type Fetcher,
  type ItemKind,
  type ItemSettingsPayload,
  type SettingValue,
} from './api';
import { authFetch } from '../../opscenter/api/auth.svelte';

export type FormStatus = 'loading' | 'ready' | 'error';

export interface FieldError {
  key: string;
  text: string;
}

export interface ItemSettingsController {
  readonly status: FormStatus;
  readonly item: ItemSettingsPayload | null;
  readonly loadError: string | null;
  readonly busyKey: string | null;
  readonly fieldError: FieldError | null;
  readonly notice: string | null;
  load(): Promise<void>;
  change(key: string, value: SettingValue | null): Promise<void>;
  readonly hasChoices: boolean;
  reset(): Promise<void>;
}

export function refusalKey(code: string): string {
  return `item_settings.error.${code}`;
}

export const FIELD_REFUSALS: readonly string[] = [
  'setting_unknown',
  'setting_type',
  'setting_below_min',
  'setting_above_max',
  'setting_not_an_option',
  'setting_too_long',
];

export function createItemSettingsController(
  kind: ItemKind,
  id: string,
  t: Translate = appT,
  fetcher: Fetcher = authFetch,
  onSaved: () => Promise<void> = () => itemSettings.refresh(true),
): ItemSettingsController {
  const held = $state<{
    status: FormStatus;
    item: ItemSettingsPayload | null;
    loadError: string | null;
    busyKey: string | null;
    fieldError: FieldError | null;
    notice: string | null;
  }>({ status: 'loading', item: null, loadError: null, busyKey: null, fieldError: null, notice: null });

  let loadSerial = 0;

  function sentence(code: string | null, key: string, error: unknown): string {
    const field = held.item?.schema?.fields[key];
    if (code && FIELD_REFUSALS.includes(code)) {
      return t(refusalKey(code), {
        min: field && field.kind === 'number' ? String(field.min ?? '') : '',
        max: field && field.kind === 'number' ? String(field.max ?? '') : '',
        length: field && field.kind === 'string' ? String(field.maxLength) : '',
      });
    }
    const reason = error instanceof Error && error.message ? error.message : t('item_settings.error.generic');
    return t('item_settings.error.save', { reason });
  }

  return {
    get status() { return held.status; },
    get item() { return held.item; },
    get loadError() { return held.loadError; },
    get busyKey() { return held.busyKey; },
    get fieldError() { return held.fieldError; },
    get notice() { return held.notice; },

    async load(): Promise<void> {
      const mine = ++loadSerial;
      held.status = held.item ? held.status : 'loading';
      try {
        const item = await readItem(kind, id, fetcher);
        if (mine !== loadSerial) return;
        held.item = item;
        held.status = 'ready';
        held.loadError = null;
      } catch (error) {
        if (mine !== loadSerial) return;
        held.status = 'error';
        held.loadError = error instanceof Error && error.message ? error.message : t('item_settings.error.load');
      }
    },

    get hasChoices() { return !!held.item && Object.keys(held.item.values).length > 0; },

    async reset(): Promise<void> {
      const stored = held.item ? Object.keys(held.item.values) : [];
      if (!stored.length) return;
      await write(stored[0]!, Object.fromEntries(stored.map((key) => [key, null])));
    },

    async change(key: string, value: SettingValue | null): Promise<void> {
      await write(key, { [key]: value });
    },
  };

  async function write(key: string, values: Record<string, SettingValue | null>): Promise<void> {
    if (held.busyKey || !held.item) return;
    held.busyKey = key;
    held.fieldError = null;
    held.notice = null;
    try {
      const answer = await writeItem(kind, id, { values, expected_revision: held.item.revision }, fetcher);
      const { status: _status, ...item } = answer;
      held.item = item;
      loadSerial += 1;
      await onSaved();
    } catch (error) {
      const refusal = refusalOf(error);
      if (refusal.code === 'item_settings_stale' && refusal.current) {
        held.item = refusal.current;
        held.notice = t('item_settings.notice.stale');
      } else {
        held.fieldError = { key: refusal.key ?? key, text: sentence(refusal.code, refusal.key ?? key, error) };
      }
    } finally {
      held.busyKey = null;
    }
  }
}

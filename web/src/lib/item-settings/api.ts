import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';
import type { WidgetSettingField, WidgetSettingsSchema } from '../../opscenter/widgets/types';
import { settingsOwner } from './settings-owner';

export type ItemKind = 'widget' | 'plugin';

export type SettingValue = boolean | number | string;

export interface ItemSettingsPayload {
  kind: ItemKind;
  id: string;
  enabled: boolean | null;
  switchable: boolean;
  values: Record<string, SettingValue>;
  dropped: string[];
  schema: WidgetSettingsSchema | null;
  revision: number;
}

export interface ItemWriteAnswer extends ItemSettingsPayload {
  status: 'committed' | 'unchanged';
}

export interface ItemNode {
  enabled?: boolean;
  values?: Record<string, SettingValue>;
  revision: number;
}

export interface ItemSettingsDocument {
  status: 'ok';
  revision: number;
  items: Partial<Record<ItemKind, Record<string, ItemNode>>>;
}

export interface WidgetRow {
  id: string;
  instancing: 'singleton' | 'per-target';
  enabled: boolean | null;
  has_settings: boolean;
}

export interface ItemPatch {
  values?: Record<string, SettingValue | null>;
  enabled?: boolean;
  expected_revision?: number;
}

export type Fetcher = typeof authFetch;

export const ITEM_SETTINGS_ROUTE = '/item-settings';

export function itemPath(kind: ItemKind, id: string): string {
  return `${ITEM_SETTINGS_ROUTE}/${kind}/${encodeURIComponent(settingsOwner(kind, id))}`;
}

export function readItem(kind: ItemKind, id: string, fetcher: Fetcher = authFetch): Promise<ItemSettingsPayload> {
  return fetcher<ItemSettingsPayload>(itemPath(kind, id));
}

export function writeItem(kind: ItemKind, id: string, patch: ItemPatch, fetcher: Fetcher = authFetch): Promise<ItemWriteAnswer> {
  return fetcher<ItemWriteAnswer>(itemPath(kind, id), { method: 'PATCH', body: JSON.stringify(patch) });
}

export interface Refusal {
  code: string | null;
  key: string | null;
  current: ItemSettingsPayload | null;
}

export function refusalOf(error: unknown): Refusal {
  const payload = error instanceof ApiError ? error.payload : null;
  const detail = payload && typeof payload === 'object' ? (payload as { detail?: unknown }).detail : null;
  if (!detail || typeof detail !== 'object') return { code: null, key: null, current: null };
  const record = detail as Record<string, unknown>;
  return {
    code: typeof record.code === 'string' ? record.code : null,
    key: typeof record.key === 'string' ? record.key : null,
    current: record.current && typeof record.current === 'object' ? (record.current as ItemSettingsPayload) : null,
  };
}

export function resolveValue(field: WidgetSettingField, stored: unknown): SettingValue {
  return fits(field, stored) ? (stored as SettingValue) : field.default;
}

export function fieldDisabled(schema: Pick<WidgetSettingsSchema, 'fields'>, key: string, stored: Readonly<Record<string, unknown>>): boolean {
  const field = schema.fields[key];
  const master = field?.kind === 'boolean' ? field.disabledWhen : undefined;
  const masterField = master ? schema.fields[master] : undefined;
  return masterField ? resolveValue(masterField, stored[master as string]) === true : false;
}

export function fits(field: WidgetSettingField, value: unknown): boolean {
  switch (field.kind) {
    case 'boolean':
      return typeof value === 'boolean';
    case 'number':
      return typeof value === 'number' && Number.isFinite(value)
        && (field.min === undefined || value >= field.min)
        && (field.max === undefined || value <= field.max);
    case 'enum':
      return typeof value === 'string' && field.options.includes(value);
    case 'string':
      return typeof value === 'string' && value.length <= field.maxLength;
    default:
      return false;
  }
}

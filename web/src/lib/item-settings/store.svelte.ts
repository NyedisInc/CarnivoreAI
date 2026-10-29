/* could not */
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { resourcePush } from '../resource-push/boot';
import { authFetch } from '../../opscenter/api/auth.svelte';
import { subscribe } from '../../opscenter/api/events.svelte';
import { manifestById } from '../../opscenter/widgets/core-manifests';
import { ITEM_SETTINGS_ROUTE, resolveValue, type ItemKind, type ItemNode, type ItemSettingsDocument, type SettingValue } from './api';
import { settingsOwner } from './settings-owner';

export const ITEM_SETTINGS_CHANGED_FRAME = 'item_settings.changed';

export const ITEM_SETTINGS_POLL_MS = 60000;

function demoDocument(): ItemSettingsDocument {
  return { status: 'ok', revision: 0, items: { widget: {}, plugin: {} } };
}

export const itemSettings: Resource<ItemSettingsDocument> = resource<ItemSettingsDocument>(
  () => authFetch<ItemSettingsDocument>(ITEM_SETTINGS_ROUTE),
  { intervalMs: ITEM_SETTINGS_POLL_MS, name: 'item-settings', demo: demoDocument, topics: ['item_settings'] },
);

subscribe(ITEM_SETTINGS_CHANGED_FRAME, (frame) => {
  if (resourcePush().isLive('item_settings')) return;
  const revision = (frame as { revision?: unknown }).revision;
  const held = itemSettings.data?.revision ?? -1;
  if (typeof revision === 'number' && revision <= held) return;
  void itemSettings.refresh(true);
});

export function storedNode(kind: ItemKind, id: string): ItemNode | undefined {
  return itemSettings.data?.items?.[kind]?.[settingsOwner(kind, id)];
}

export function isWidgetDisabled(widgetId: string): boolean {
  return storedNode('widget', widgetId)?.enabled === false;
}

export function widgetSetting(widgetId: string, key: string): SettingValue {
  const field = manifestById(widgetId)?.settings?.fields[key];
  if (!field) throw new Error(`${widgetId} declares no setting ${key}`);
  return resolveValue(field, storedNode('widget', widgetId)?.values?.[key]);
}

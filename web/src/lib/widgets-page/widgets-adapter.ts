/*  hidden
 */
import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import { isViewCell } from '../../opscenter/widgets/views';
import { authFetch } from '../../opscenter/api/auth.svelte';
import { homeLayout, terminalLayout } from '../../opscenter/engine/layout.svelte';
import type { SlotId } from '../../opscenter/engine/types';
import { itemSettings } from '../item-settings/store.svelte';
import { writeItem, type Fetcher, type WidgetRow } from '../item-settings/api';
import type { WidgetManifest } from '../../opscenter/widgets/types';
import type { ManagerAdapter, ManagerItem } from '../manager-frame/types';
import type { Translate } from '../sessions/types';

export interface WidgetItem extends ManagerItem {
    readonly manifest: WidgetManifest;
}

export function factKey(group: 'category' | 'canvas' | 'capability' | 'instancing', value: string): string {
    return `widgets.page.${group}.${value.replace(/-/g, '_')}`;
}

export function toWidgetItem(manifest: WidgetManifest, t: Translate, enabled: boolean | null = null): WidgetItem {
    const marks = [t(factKey('category', manifest.category))];
    if (manifest.instancing === 'per-target') marks.push(t(factKey('instancing', manifest.instancing)));
    return {
        id: manifest.id,
        name: t(manifest.titleKey),
        brief: t('widgets.page.brief', {
            pages: manifest.canvases.map((canvas) => t(factKey('canvas', canvas))).join(', '),
        }),
        meta: manifest.version,
        marks,
        enabled,
        manifest,
    };
}

export const WIDGETS_ROUTE = '/widgets';

export function hideOnThisDevice(widgetId: string): void {
  const cell = widgetId.replace(/^core\./, '') as SlotId;
  homeLayout.hide(cell);
  if (terminalLayout.session) terminalLayout.hide(cell);
}

export function createWidgetsAdapter(
  t: Translate,
  manifests: Readonly<Record<string, WidgetManifest>> = CORE_MANIFESTS,
  fetcher: Fetcher = authFetch,
  onChanged: () => Promise<void> = () => itemSettings.refresh(true),
  onSwitchedOff: (widgetId: string) => void = hideOnThisDevice,
): ManagerAdapter {
  return {
    async list(): Promise<readonly ManagerItem[]> {
      const body = await fetcher<{ widgets: WidgetRow[] }>(WIDGETS_ROUTE);
      const state = new Map((body?.widgets ?? []).map((row) => [row.id, row.enabled]));
      return Object.values(manifests).filter((manifest) => !isViewCell(manifest)).map((manifest) => toWidgetItem(manifest, t, state.get(manifest.id) ?? null));
    },
    async setEnabled(id: string, enabled: boolean): Promise<ManagerItem> {
      const answer = await writeItem('widget', id, { enabled }, fetcher);
      const on = answer.enabled !== false;
      await onChanged();
      if (!on) onSwitchedOff(id);
      const manifest = manifests[id];
      if (!manifest) throw new Error(t('widgets.page.unknown', { id }));
      return toWidgetItem(manifest, t, on);
    },
  };
}

/* the widgets page */

import type { CellId, LayoutPage, SlotId } from '../engine/types';
import { CORE_MANIFESTS } from '../widgets/core-manifests';
import { drawingIds, isViewCell } from '../widgets/views';
import type { WidgetCategory, WidgetManifest } from '../widgets/types';

export type DrawerItemState = 'addable' | 'placed';

export interface DrawerItem {
  widgetId: string;
  cell: CellId;
  manifest: WidgetManifest;
  title: string;
  state: DrawerItemState;
}

export interface DrawerInputs {
  page: LayoutPage;
  onSurface: readonly SlotId[];
  disabled: (widgetId: string) => boolean;
  query: string;
  category: WidgetCategory | null;
  t: (key: string) => string;
  manifests?: Readonly<Record<string, WidgetManifest>>;
}

/* the widgets page */
export function categoryKey(category: WidgetCategory): string {
  return `widgets.page.category.${category}`;
}

function cellOf(widgetId: string): CellId | null {
  return widgetId.startsWith('core.') ? (widgetId.slice('core.'.length) as CellId) : null;
}

export function offered(input: DrawerInputs): DrawerItem[] {
  const manifests = input.manifests ?? CORE_MANIFESTS;
  const on = new Set<string>(input.onSurface);
  const addable: DrawerItem[] = [];
  const placed: DrawerItem[] = [];
  for (const manifest of Object.values(manifests)) {
    if (manifest.instancing !== 'singleton') continue;
    if (isViewCell(manifest)) continue;
    if (input.disabled(manifest.id)) continue;
    const cell = cellOf(manifest.id);
    if (!cell) continue;
    const item = (state: DrawerItemState): DrawerItem => ({
      widgetId: manifest.id,
      cell,
      manifest,
      title: input.t(manifest.titleKey),
      state,
    });
    if (drawingIds(manifest).some((id) => on.has(id.slice('core.'.length)))) placed.push(item('placed'));
    else addable.push(item('addable'));
  }
  return [...addable, ...placed];
}

export function drawerItems(input: DrawerInputs): DrawerItem[] {
  return offered(input).filter((item) =>
    passesFilter(input, item.manifest.category, [item.title, input.t(categoryKey(item.manifest.category)), item.widgetId]),
  );
}

export function passesFilter(
  input: Pick<DrawerInputs, 'query' | 'category'>,
  category: WidgetCategory,
  words: readonly string[],
): boolean {
  if (input.category && category !== input.category) return false;
  const needle = input.query.trim().toLowerCase();
  if (!needle) return true;
  return words.join(' ').toLowerCase().includes(needle);
}

export function chipCategories(items: readonly DrawerItem[], order: readonly WidgetCategory[]): WidgetCategory[] {
  const present = new Set(items.map((item) => item.manifest.category));
  return order.filter((category) => present.has(category));
}

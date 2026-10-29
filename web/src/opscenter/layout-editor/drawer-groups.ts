
import { CORE_MANIFESTS } from '../widgets/core-manifests';
import { drawingIds, isViewCell } from '../widgets/views';
import { WIDGET_CATEGORIES, WIDGET_TYPES, type WidgetCategory, type WidgetManifest, type WidgetType } from '../widgets/types';
import { kindOf } from '../engine/meta';
import { panels } from '../engine/plugin-kinds';
import type { CellId, SlotId } from '../engine/types';
import { categoryKey, passesFilter } from './drawer-model';

export type GroupRowState = 'addable' | 'placed' | 'refused';

export type RowRefusal = 'disabled';

export interface GroupRow {
  widgetId: string;
  cell: CellId | null;
  manifest: WidgetManifest;
  title: string;
  type: WidgetType;
  family: boolean;
  state: GroupRowState;
  placed: number;
  refusal: RowRefusal | null;
  reason: string;
  sentence: string;
}

export interface DrawerGroup {
  category: WidgetCategory;
  rows: GroupRow[];
}

export interface GroupInputs {
  onSurface: readonly SlotId[];
  disabled: (widgetId: string) => boolean;
  query: string;
  kind?: WidgetType | null;
  extraWords?: Readonly<Record<string, readonly string[]>>;
  t: (key: string, params?: Record<string, string | number>) => string;
  manifests?: Readonly<Record<string, WidgetManifest>>;
}

export interface FlatList {
  rows: GroupRow[];
}

export interface GroupedList {
  groups: DrawerGroup[];
}

/* the widgets page */
export function refusalWords(title: string, t: GroupInputs['t']): { reason: string; sentence: string } {
  return { reason: t('layout_editor.refuse.disabled_short'), sentence: t('layout_editor.refuse.disabled', { title }) };
}

export function isPanelRow(row: { manifest: WidgetManifest }): boolean {
  return panels().isPanel(row.manifest.id);
}

function copiesOn(manifest: WidgetManifest, onSurface: readonly SlotId[]): number {
  if (panels().isPanel(manifest.id)) return onSurface.filter((slot) => kindOf(slot) === manifest.id).length;
  const keys = drawingIds(manifest).map((id) => id.slice('core.'.length));
  return onSurface.filter((slot) => keys.includes(kindOf(slot) ?? slot)).length;
}

export function groupRows(input: GroupInputs): GroupRow[] {
  const manifests = input.manifests ?? { ...CORE_MANIFESTS, ...panels().manifests() };
  const rows: GroupRow[] = [];
  for (const manifest of Object.values(manifests)) {
    if (isViewCell(manifest)) continue;
    const family = manifest.instancing === 'per-target';
    if (family && manifest.type === 'pane') continue;
    const key = manifest.id.slice('core.'.length);
    const cell = family || !manifest.id.startsWith('core.') ? null : (key as CellId);
    const title = input.t(manifest.titleKey);
    const placed = copiesOn(manifest, input.onSurface);
    const refusal: RowRefusal | null = input.disabled(manifest.id) ? 'disabled' : null;
    const words = refusal ? refusalWords(title, input.t) : { reason: '', sentence: '' };
    rows.push({
      widgetId: manifest.id,
      cell,
      manifest,
      title,
      type: manifest.type,
      family,
      state: refusal ? 'refused' : (family && !panels().isPanel(manifest.id)) || placed === 0 ? 'addable' : 'placed',
      placed: refusal ? 0 : placed,
      refusal,
      ...words,
    });
  }
  return rows;
}

export function drawerGroups(input: GroupInputs): GroupedList {
  const kind = input.kind ?? null;
  const matched = groupRows(input).filter((row) => (kind === null || row.type === kind) &&
    passesFilter({ query: input.query, category: null }, row.manifest.category, [
      row.title,
      input.t(categoryKey(row.manifest.category)),
      input.t(`widgets.type.${row.type}`),
      row.widgetId,
      ...(input.extraWords?.[row.widgetId] ?? []),
    ]),
  );
  const rank: Record<GroupRowState, number> = { addable: 0, placed: 1, refused: 2 };
  const groups = WIDGET_CATEGORIES.map((category) => ({
    category,
    rows: matched.filter((row) => row.manifest.category === category).sort((a, b) => rank[a.state] - rank[b.state]),
  })).filter((group) => group.rows.length > 0);
  return { groups };
}


export function drawerList(input: GroupInputs): FlatList {
  const grouped = drawerGroups(input);
  const rank: Record<GroupRowState, number> = { addable: 0, placed: 1, refused: 2 };
  const rows = grouped.groups.flatMap((group) => group.rows);
  rows.sort((a, b) => rank[a.state] - rank[b.state]);
  return { rows };
}

export function listKinds(input: GroupInputs): WidgetType[] {
  const present = new Set(groupRows(input).map((row) => row.type));
  return WIDGET_TYPES.filter((type) => present.has(type));
}

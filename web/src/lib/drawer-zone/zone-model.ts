
import { CORE_MANIFESTS, manifestById } from '../../opscenter/widgets/core-manifests';
import type { WidgetLook, WidgetManifest } from '../../opscenter/widgets/types';
import { hasViews, mergedIds, mergePlacement, viewOfPlacement } from '../../opscenter/widgets/views';
import { hasPlacementOptions, hasRepeatableOptions, isRetiredPlacementKey, type PlacementOptions, type PlacementOptionValue } from '../../opscenter/widgets/placement-options';
import { OPTION_KEY_RE, normalizeOptionValues } from './option-values';
import { HEADER_OPTION } from '../../opscenter/shell/widget-head';

export const ZONE_FIELD = 'drawer_zone';

export const MAX_ZONE_ITEMS = 12;

export const ZONE_CELL_HEIGHT = 168;

export interface ZoneItem {
  widget: string;
  look: WidgetLook | null;
  target?: string;
  view?: string;
  instance?: string;
  options?: PlacementOptions;
}

export const MAX_ZONE_ITEM_OPTIONS = 32;

export const ZONE_INSTANCE_RE = /^i[0-9]{1,3}$/;

export const ZONE_VIEW_RE = /^[a-z][a-z0-9-]{0,31}$/;

const MERGED = mergedIds(CORE_MANIFESTS);

export const ZONE_TARGET_RE = /^[A-Za-z0-9@][A-Za-z0-9:@._-]{0,127}$/;

export function zoneItemKey(item: Pick<ZoneItem, 'widget' | 'target'> & { instance?: string | null }): string {
  const base = item.target ? `${item.widget}@${item.target}` : item.widget;
  return item.instance ? `${base}#${item.instance}` : base;
}

export function isRepeatable(widget: string): boolean {
  return hasViews(manifestById(widget)) || hasRepeatableOptions(widget);
}

export function freshInstance(items: readonly Pick<ZoneItem, 'widget' | 'target' | 'instance'>[], widget: string, target?: string): string | undefined {
  const taken = new Set(items.map((item) => zoneItemKey(item)));
  if (!taken.has(zoneItemKey({ widget, target }))) return undefined;
  for (let n = 2; n < 1000; n += 1) {
    if (!taken.has(zoneItemKey({ widget, target, instance: `i${n}` }))) return `i${n}`;
  }
  return undefined;
}

export const DEFAULT_ZONE_ITEMS: readonly ZoneItem[] = Object.freeze([{ widget: 'core.ledger', look: null }]);

const LOOKS: readonly string[] = ['compact', 'full'];

export function normalizeZone(raw: unknown, max: number = MAX_ZONE_ITEMS): ZoneItem[] | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const list = (raw as { items?: unknown }).items;
  if (!Array.isArray(list)) return null;
  const seen = new Set<string>();
  const items: ZoneItem[] = [];
  for (const entry of list) {
    if (!entry || typeof entry !== 'object') continue;
    const { widget: stored, look, target, view: storedView, instance: storedInstance, options: storedOptions } = entry as { widget?: unknown; look?: unknown; target?: unknown; view?: unknown; instance?: unknown; options?: unknown };
    if (typeof stored !== 'string' || !stored) continue;
    const { widget, view } = mergePlacement(
      { widget: stored, view: typeof storedView === 'string' && ZONE_VIEW_RE.test(storedView) ? storedView : undefined },
      MERGED,
    );
    const aim = typeof target === 'string' && ZONE_TARGET_RE.test(target) ? target : undefined;
    let instance = typeof storedInstance === 'string' && ZONE_INSTANCE_RE.test(storedInstance) ? storedInstance : undefined;
    let key = zoneItemKey({ widget, target: aim, instance });
    if (seen.has(key)) {
      if (!isRepeatable(widget)) continue;
      instance = freshInstance(items, widget, aim);
      key = zoneItemKey({ widget, target: aim, instance });
      if (seen.has(key)) continue;
    }
    seen.add(key);
    const item: ZoneItem = { widget, look: typeof look === 'string' && LOOKS.includes(look) ? (look as WidgetLook) : null };
    if (aim) item.target = aim;
    if (view) item.view = view;
    if (instance) item.instance = instance;
    const options = normalizeOptionValues(storedOptions, MAX_ZONE_ITEM_OPTIONS);
    if (Object.keys(options).length > 0) item.options = options;
    items.push(item);
    if (items.length >= max) break;
  }
  return items;
}

export function toStored(items: readonly ZoneItem[]): { v: 1; items: { widget: string; look?: WidgetLook; target?: string; view?: string; instance?: string; options?: PlacementOptions }[] } {
  return {
    v: 1,
    items: items.map((item) => ({
      widget: item.widget,
      ...(item.look ? { look: item.look } : {}),
      ...(item.target ? { target: item.target } : {}),
      ...(item.view ? { view: item.view } : {}),
      ...(item.instance ? { instance: item.instance } : {}),
      ...(item.options && Object.keys(item.options).length > 0 ? { options: { ...item.options } } : {}),
    })),
  };
}

export function lookOf(manifest: WidgetManifest | undefined, item: ZoneItem): WidgetLook | null {
  const looks = manifest?.looks;
  if (!looks) return null;
  if (item.look && looks.names.includes(item.look)) return item.look;
  return looks.defaults.drawer ?? looks.names[0] ?? null;
}

export function addItem(items: readonly ZoneItem[], widget: string, index?: number, target?: string, max: number = MAX_ZONE_ITEMS): ZoneItem[] {
  const instance = isRepeatable(widget) ? freshInstance(items, widget, target) : undefined;
  const key = zoneItemKey({ widget, target, instance });
  if (items.some((item) => zoneItemKey(item) === key) || items.length >= max) return [...items];
  const at = index === undefined ? items.length : Math.max(0, Math.min(index, items.length));
  const next = [...items];
  next.splice(at, 0, { widget, look: null, ...(target ? { target } : {}), ...(instance ? { instance } : {}) });
  return next;
}

export function removeItem(items: readonly ZoneItem[], key: string): ZoneItem[] {
  return items.filter((item) => zoneItemKey(item) !== key);
}

export function moveItem(items: readonly ZoneItem[], key: string, index: number): ZoneItem[] {
  const from = items.findIndex((item) => zoneItemKey(item) === key);
  if (from < 0) return [...items];
  const rest = items.filter((item) => zoneItemKey(item) !== key);
  const at = Math.max(0, Math.min(index, rest.length));
  return [...rest.slice(0, at), items[from] as ZoneItem, ...rest.slice(at)];
}

export function stepItem(items: readonly ZoneItem[], key: string, direction: -1 | 1): ZoneItem[] {
  const from = items.findIndex((item) => zoneItemKey(item) === key);
  const to = from + direction;
  if (from < 0 || to < 0 || to >= items.length) return [...items];
  return moveItem(items, key, to);
}

export function setItemLook(items: readonly ZoneItem[], key: string, look: WidgetLook): ZoneItem[] {
  const found = items.find((item) => zoneItemKey(item) === key);
  const manifest = found ? manifestById(found.widget) : undefined;
  if (!manifest?.looks?.names.includes(look)) return [...items];
  return items.map((item) => (zoneItemKey(item) === key ? { ...item, look } : item));
}

export function setItemView(items: readonly ZoneItem[], key: string, view: string): ZoneItem[] {
  const found = items.find((item) => zoneItemKey(item) === key);
  const manifest = found ? manifestById(found.widget) : undefined;
  const chosen = manifest?.views?.find((one) => one.id === view);
  if (!found || !chosen) return [...items];
  const first = viewOfPlacement(manifest, null)?.id;
  return items.map((item) => {
    if (zoneItemKey(item) !== key) return item;
    const { view: _old, ...rest } = item;
    return chosen.id === first ? rest : { ...rest, view: chosen.id };
  });
}

export function setItemOption(items: readonly ZoneItem[], key: string, option: string, value: PlacementOptionValue | null): ZoneItem[] {
  const found = items.find((item) => zoneItemKey(item) === key);
  if (!found || (option !== HEADER_OPTION && !hasPlacementOptions(found.widget)) || !OPTION_KEY_RE.test(option)) return [...items];
  return items.map((item) => {
    if (zoneItemKey(item) !== key) return item;
    const { options: _old, ...rest } = item;
    const next: Record<string, PlacementOptionValue> = Object.fromEntries(Object.entries(item.options ?? {}).filter(([k]) => !isRetiredPlacementKey(item.widget, k)));
    if (value === null) delete next[option];
    else next[option] = value;
    return Object.keys(next).length > 0 ? { ...rest, options: next } : rest;
  });
}

export function resetItemOptions(items: readonly ZoneItem[], key: string): ZoneItem[] {
  return items.map((item) => {
    if (zoneItemKey(item) !== key) return item;
    const { options: old, ...rest } = item;
    const header = old?.[HEADER_OPTION];
    return typeof header === 'boolean' ? { ...rest, options: { [HEADER_OPTION]: header } } : rest;
  });
}

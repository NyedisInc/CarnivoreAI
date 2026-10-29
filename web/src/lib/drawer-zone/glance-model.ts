
import { zoneItemKey, type ZoneItem } from './zone-model';
import { OPTION_KEY_RE, normalizeOptionValues } from './option-values';
import type { PlacementOptionValue } from '../../opscenter/widgets/placement-options';

export const MAX_GLANCE_PLACEMENTS = 12;

export const MAX_PLACEMENT_OPTIONS = 8;


/* the glance area */
export const FAMILY_TARGET_OPTION = 'target';

export type { PlacementOptionValue };

/* the glance area */
export interface GlancePlacement {
  id: string;
  widget: string;
  options: Readonly<Record<string, PlacementOptionValue>>;
}

const ID_RE = /^[a-z0-9][a-z0-9-]{0,31}$/;

export function newPlacementId(taken: ReadonlySet<string>, random: () => number = Math.random): string {
  for (;;) {
    const id = `g-${Math.floor(random() * 36 ** 6).toString(36).padStart(6, '0')}`;
    if (!taken.has(id)) return id;
  }
}

export function normalizeGlance(raw: unknown): GlancePlacement[] | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const list = (raw as { glance?: unknown }).glance;
  if (!Array.isArray(list)) return null;
  const seen = new Set<string>();
  const out: GlancePlacement[] = [];
  for (const entry of list) {
    if (!entry || typeof entry !== 'object') continue;
    const { id, widget, options } = entry as { id?: unknown; widget?: unknown; options?: unknown };
    if (typeof id !== 'string' || !ID_RE.test(id) || seen.has(id)) continue;
    if (typeof widget !== 'string' || !widget) continue;
    seen.add(id);
    out.push({ id, widget, options: normalizeOptionValues(options, MAX_PLACEMENT_OPTIONS) });
    if (out.length >= MAX_GLANCE_PLACEMENTS) break;
  }
  return out;
}

export function derivedGlance(items: readonly ZoneItem[]): GlancePlacement[] {
  return items.slice(0, MAX_GLANCE_PLACEMENTS).map((item) => ({
    id: `d-${zoneItemKey(item).toLowerCase().replace(/[^a-z0-9]+/g, '-')}`.slice(0, 32).replace(/-+$/, ''),
    widget: item.widget,
    options: (item.target ? { [FAMILY_TARGET_OPTION]: item.target } : {}) as Record<string, PlacementOptionValue>,
  }));
}

export function glanceToStored(list: readonly GlancePlacement[]): { id: string; widget: string; options?: Record<string, PlacementOptionValue> }[] {
  return list.map((p) => (Object.keys(p.options).length ? { id: p.id, widget: p.widget, options: { ...p.options } } : { id: p.id, widget: p.widget }));
}

/* the glance area */
export function addPlacement(
  list: readonly GlancePlacement[],
  widget: string,
  repeatable: boolean,
  index?: number,
  options: Readonly<Record<string, PlacementOptionValue>> = {},
): GlancePlacement[] {
  if (list.length >= MAX_GLANCE_PLACEMENTS) return [...list];
  if (!repeatable && list.some((p) => p.widget === widget)) return [...list];
  const at = index === undefined ? list.length : Math.max(0, Math.min(index, list.length));
  const next = [...list];
  next.splice(at, 0, { id: newPlacementId(new Set(list.map((p) => p.id))), widget, options: normalizeOptionValues(options, MAX_PLACEMENT_OPTIONS) });
  return next;
}

export function removePlacement(list: readonly GlancePlacement[], id: string): GlancePlacement[] {
  return list.filter((p) => p.id !== id);
}

export function movePlacement(list: readonly GlancePlacement[], id: string, index: number): GlancePlacement[] {
  const from = list.findIndex((p) => p.id === id);
  if (from < 0) return [...list];
  const rest = list.filter((p) => p.id !== id);
  const at = Math.max(0, Math.min(index, rest.length));
  return [...rest.slice(0, at), list[from] as GlancePlacement, ...rest.slice(at)];
}

export function setPlacementWidget(list: readonly GlancePlacement[], id: string, widget: string): GlancePlacement[] {
  return list.map((p) => (p.id === id && widget ? { ...p, widget } : p));
}

export function setPlacementOption(
  list: readonly GlancePlacement[],
  id: string,
  key: string,
  value: PlacementOptionValue | null,
): GlancePlacement[] {
  if (!OPTION_KEY_RE.test(key)) return [...list];
  return list.map((p) => {
    if (p.id !== id) return p;
    const options = { ...p.options };
    if (value === null) delete options[key];
    else options[key] = value;
    return { ...p, options };
  });
}

import { freshInstance, isRepeatable, normalizeZone, resetItemOptions, setItemOption, setItemView, toStored, zoneItemKey, type ZoneItem } from '../drawer-zone/zone-model';
import type { PlacementOptionValue } from '../../opscenter/widgets/placement-options';
import { RAIL_MAX_SECTIONS, RAIL_RATIO_DEFAULT, RAIL_RATIO_MAX, RAIL_RATIO_MIN, type RailBand } from './rail-model';

export interface RailLayout {
  sections: ZoneItem[][];
  ratio: number;
}

export interface RailSpot {
  section: number;
  index: number;
  split: RailBand | null;
}

export interface StoredRail {
  v: 2;
  sections: { items: ReturnType<typeof toStored>['items'] }[];
  ratio?: number;
}

export function clampRatio(raw: unknown): number {
  if (typeof raw !== 'number' || !Number.isFinite(raw)) return RAIL_RATIO_DEFAULT;
  return Math.round(Math.min(RAIL_RATIO_MAX, Math.max(RAIL_RATIO_MIN, raw)) * 1000) / 1000;
}

export function singleSection(items: readonly ZoneItem[]): RailLayout {
  return { sections: [items.map((item) => ({ ...item }))], ratio: RAIL_RATIO_DEFAULT };
}

export function tidyRail(layout: RailLayout): RailLayout {
  const kept = layout.sections.filter((section) => section.length > 0).slice(0, RAIL_MAX_SECTIONS);
  if (kept.length < 2) return { sections: [kept[0] ?? []], ratio: RAIL_RATIO_DEFAULT };
  return { sections: kept, ratio: clampRatio(layout.ratio) };
}

export function normalizeRail(raw: unknown, max: number): RailLayout | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const sections = (raw as { sections?: unknown }).sections;
  if (!Array.isArray(sections)) {
    const flat = normalizeZone(raw, max);
    return flat ? singleSection(flat) : null;
  }
  const seen = new Set<string>();
  let room = max;
  const kept: ZoneItem[][] = [];
  for (const section of sections.slice(0, RAIL_MAX_SECTIONS)) {
    const items = section && typeof section === 'object' ? (section as { items?: unknown }).items : undefined;
    const list = (normalizeZone({ items }, max) ?? []).filter((item) => {
      const key = zoneItemKey(item);
      if (seen.has(key) || room <= 0) return false;
      seen.add(key);
      room -= 1;
      return true;
    });
    kept.push(list);
  }
  return tidyRail({ sections: kept, ratio: clampRatio((raw as { ratio?: unknown }).ratio) });
}

export function railToStored(layout: RailLayout): StoredRail {
  const tidy = tidyRail(layout);
  const stored: StoredRail = { v: 2, sections: tidy.sections.map((section) => ({ items: toStored(section).items })) };
  if (tidy.sections.length === 2) stored.ratio = tidy.ratio;
  return stored;
}

export function flatItems(layout: RailLayout): ZoneItem[] {
  return layout.sections.flat();
}

export function sectionOf(layout: RailLayout, key: string): number {
  return layout.sections.findIndex((section) => section.some((item) => zoneItemKey(item) === key));
}

export function canSplit(layout: RailLayout, carried: string | null): boolean {
  if (layout.sections.length >= RAIL_MAX_SECTIONS) return false;
  return flatItems(layout).some((item) => zoneItemKey(item) !== carried);
}

export function removeFromRail(layout: RailLayout, key: string): RailLayout {
  return tidyRail({ sections: layout.sections.map((section) => section.filter((item) => zoneItemKey(item) !== key)), ratio: layout.ratio });
}

export function placeInLayout(layout: RailLayout, spot: RailSpot, widget: string, target: string | undefined, max: number, instance?: string | null, carried?: ZoneItem): RailLayout {
  const held = flatItems(layout);
  const fresh = instance === undefined && isRepeatable(widget) ? freshInstance(held, widget, target) : undefined;
  let own = instance ?? fresh;
  let key = zoneItemKey({ widget, target, instance: own });
  const moving = !carried && sectionOf(layout, key) >= 0;
  if (carried && sectionOf(layout, key) >= 0) {
    own = freshInstance(held, widget, target);
    key = zoneItemKey({ widget, target, instance: own });
  }
  if (!moving && held.length >= max) return { ...layout, sections: layout.sections.map((s) => [...s]) };
  const old = moving ? held.find((item) => zoneItemKey(item) === key) : carried;
  const base: ZoneItem = old ? { ...old } : target ? { widget, look: null, target } : { widget, look: null };
  const { instance: _drop, ...bare } = base;
  const item: ZoneItem = own ? { ...bare, instance: own } : bare;
  const sections = layout.sections.map((section) => section.filter((one) => zoneItemKey(one) !== key));
  if (spot.split) {
    const rest = sections.filter((section) => section.length > 0);
    if (rest.length < RAIL_MAX_SECTIONS) {
      const ratio = layout.sections.length === RAIL_MAX_SECTIONS ? layout.ratio : RAIL_RATIO_DEFAULT;
      return tidyRail({ sections: spot.split === 'start' ? [[item], ...rest] : [...rest, [item]], ratio });
    }
    const at = spot.split === 'start' ? 0 : sections.length - 1;
    sections[at] = spot.split === 'start' ? [item, ...sections[at]!] : [...sections[at]!, item];
    return tidyRail({ sections, ratio: layout.ratio });
  }
  const at = Math.max(0, Math.min(spot.section, sections.length - 1));
  const list = sections[at]!;
  const index = Math.max(0, Math.min(spot.index, list.length));
  sections[at] = [...list.slice(0, index), item, ...list.slice(index)];
  return tidyRail({ sections, ratio: layout.ratio });
}

export function stepInRail(layout: RailLayout, key: string, direction: -1 | 1): RailLayout {
  const at = sectionOf(layout, key);
  if (at < 0) return layout;
  const list = layout.sections[at]!;
  const from = list.findIndex((item) => zoneItemKey(item) === key);
  const to = from + direction;
  if (to < 0 || to >= list.length) return layout;
  const next = [...list];
  [next[from], next[to]] = [next[to]!, next[from]!];
  return { ...layout, sections: layout.sections.map((section, i) => (i === at ? next : section)) };
}

/* bottom: 0 left: 0; the closed rail */
export function sectionStyle(axis: 'x' | 'y', section: number, count: number, ratio: number): string {
  const [start, end, a, b] = axis === 'y' ? ['top', 'bottom', 'left', 'right'] : ['left', 'right', 'top', 'bottom'];
  const cut = splitAt(ratio);
  const share = count < 2 ? `${start}: 0; ${end}: 0` : section === 0 ? `${start}: 0; ${end}: calc(100% - ${cut})` : `${start}: ${cut}; ${end}: 0`;
  return `${share}; ${a}: 0; ${b}: 0`;
}

export function splitAt(ratio: number): string {
  return `${Math.round(clampRatio(ratio) * 1000) / 10}%`;
}

export function setViewInRail(layout: RailLayout, key: string, view: string): RailLayout {
  return { ...layout, sections: layout.sections.map((section) => setItemView(section, key, view)) };
}

export function setOptionInRail(layout: RailLayout, key: string, option: string, value: PlacementOptionValue | null): RailLayout {
  return { ...layout, sections: layout.sections.map((section) => setItemOption(section, key, option, value)) };
}

export function resetOptionsInRail(layout: RailLayout, key: string): RailLayout {
  return { ...layout, sections: layout.sections.map((section) => resetItemOptions(section, key)) };
}

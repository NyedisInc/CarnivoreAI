import { freshInstance, isRepeatable, normalizeZone, resetItemOptions, setItemOption, setItemView, toStored, zoneItemKey, type ZoneItem } from '../drawer-zone/zone-model';
import type { PlacementOptionValue } from '../../opscenter/widgets/placement-options';
import { RAIL_MAX_SECTIONS, RAIL_MIN_SHARE, RAIL_RATIO_DEFAULT, RAIL_V2_MAX_SECTIONS } from './rail-model';
import { canHalve, dropCut, halveAt, repairCuts, round3 } from './rail-cuts';

export interface RailLayout {
  sections: ZoneItem[][];
  cuts: number[];
}

export interface RailSpot {
  section: number;
  index: number;
  split: boolean;
}

type StoredSection = { items: ReturnType<typeof toStored>['items'] };

export interface StoredRailV2 {
  v: 2;
  sections: StoredSection[];
  ratio?: number;
}

export interface StoredRailV3 {
  v: 3;
  sections: StoredSection[];
  cuts: number[];
}

export type StoredRail = StoredRailV2 | StoredRailV3;

export function clampRatio(raw: unknown): number {
  if (typeof raw !== 'number' || !Number.isFinite(raw)) return RAIL_RATIO_DEFAULT;
  return round3(Math.min(1 - RAIL_MIN_SHARE, Math.max(RAIL_MIN_SHARE, raw)));
}

export function singleSection(items: readonly ZoneItem[]): RailLayout {
  return { sections: [items.map((item) => ({ ...item }))], cuts: [] };
}

export function tidyRail(layout: RailLayout): RailLayout {
  const sections = layout.sections.map((section) => [...section]);
  let cuts = repairCuts(layout.cuts, sections.length);
  for (let i = sections.length - 1; i >= 0 && sections.length > 1; i -= 1) {
    if (sections[i]!.length > 0) continue;
    sections.splice(i, 1);
    cuts = dropCut(cuts, i);
  }
  if (sections.length > RAIL_MAX_SECTIONS) {
    sections.length = RAIL_MAX_SECTIONS;
    cuts = cuts.slice(0, RAIL_MAX_SECTIONS - 1);
  }
  return { sections, cuts };
}

function storedCuts(raw: object, count: number): number[] {
  const { cuts, ratio } = raw as { cuts?: unknown; ratio?: unknown };
  if (Array.isArray(cuts)) return cuts as number[];
  return count === 2 ? [clampRatio(ratio)] : [];
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
  return tidyRail({ sections: kept, cuts: storedCuts(raw, kept.length) });
}

export function railToStored(layout: RailLayout): StoredRail {
  const tidy = tidyRail(layout);
  const sections = tidy.sections.map((section) => ({ items: toStored(section).items }));
  if (sections.length > RAIL_V2_MAX_SECTIONS) return { v: 3, sections, cuts: tidy.cuts };
  const stored: StoredRailV2 = { v: 2, sections };
  if (sections.length === 2) stored.ratio = tidy.cuts[0]!;
  return stored;
}

export function flatItems(layout: RailLayout): ZoneItem[] {
  return layout.sections.flat();
}

export function sectionOf(layout: RailLayout, key: string): number {
  return layout.sections.findIndex((section) => section.some((item) => zoneItemKey(item) === key));
}

export function canSplitAt(layout: RailLayout, section: number, carried: string | null): boolean {
  const here = layout.sections[section];
  if (!here || layout.sections.length >= RAIL_MAX_SECTIONS || !canHalve(layout.cuts, section)) return false;
  return here.some((item) => zoneItemKey(item) !== carried);
}

export function removeFromRail(layout: RailLayout, key: string): RailLayout {
  return tidyRail({ sections: layout.sections.map((section) => section.filter((item) => zoneItemKey(item) !== key)), cuts: layout.cuts });
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
  if (!moving && held.length >= max) return copyOf(layout);
  const old = moving ? held.find((item) => zoneItemKey(item) === key) : carried;
  const base: ZoneItem = old ? { ...old } : target ? { widget, look: null, target } : { widget, look: null };
  const { instance: _drop, ...bare } = base;
  const item: ZoneItem = own ? { ...bare, instance: own } : bare;
  const sections = layout.sections.map((section) => section.filter((one) => zoneItemKey(one) !== key));
  if (spot.split) return splitInto(layout, sections, spot.section, item);
  const at = Math.max(0, Math.min(spot.section, sections.length - 1));
  const list = sections[at]!;
  const index = Math.max(0, Math.min(spot.index, list.length));
  sections[at] = [...list.slice(0, index), item, ...list.slice(index)];
  return tidyRail({ sections, cuts: layout.cuts });
}

function copyOf(layout: RailLayout): RailLayout {
  return { sections: layout.sections.map((section) => [...section]), cuts: [...layout.cuts] };
}

function splitInto(layout: RailLayout, without: ZoneItem[][], section: number, item: ZoneItem): RailLayout {
  const at = Math.max(0, Math.min(section, without.length - 1));
  const cuts = repairCuts(layout.cuts, without.length);
  if (!canHalve(cuts, at)) return copyOf(layout);
  const next = without.map((one) => [...one]);
  next.splice(at + 1, 0, [item]);
  if (next.filter((one) => one.length > 0).length > RAIL_MAX_SECTIONS) return copyOf(layout);
  return tidyRail({ sections: next, cuts: halveAt(cuts, at) });
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

export function setViewInRail(layout: RailLayout, key: string, view: string): RailLayout {
  return { ...layout, sections: layout.sections.map((section) => setItemView(section, key, view)) };
}

export function setOptionInRail(layout: RailLayout, key: string, option: string, value: PlacementOptionValue | null): RailLayout {
  return { ...layout, sections: layout.sections.map((section) => setItemOption(section, key, option, value)) };
}

export function resetOptionsInRail(layout: RailLayout, key: string): RailLayout {
  return { ...layout, sections: layout.sections.map((section) => resetItemOptions(section, key)) };
}

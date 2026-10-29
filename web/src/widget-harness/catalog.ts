
import { CORE_MANIFESTS } from '../opscenter/widgets/core-manifests';
import { SIZE_UNIT_PX, fitsForSlot, suggestedSizes } from '../opscenter/widgets/fits';
import { GLANCE_TILE_HEIGHT_PX } from '../lib/drawer-zone/glance';
import { declaredGlanceHeight } from '../opscenter/widgets/glance-declarations';
import { standardSizes, type StandardSize } from '../opscenter/widgets/standard-sizes';
import { META, metaFor } from '../opscenter/engine/meta';
import { PRESETS } from '../opscenter/viz/presets';
import { VIZ_SPECS } from '../opscenter/viz/specs';
import { fixtureChartId } from '../opscenter/widgets/fixtures/ids';
import type { SlotId } from '../opscenter/engine/types';
import type { FitZone } from '../opscenter/widgets/types';

export const HARNESS_ZONES: readonly FitZone[] = ['home', 'terminal', 'drawer'];

export const FIXTURE_TERMINAL_SLOT: SlotId = 'terminal:row:9001';
export const FIXTURE_BROWSER_SLOT: SlotId = 'browser:fx-browser';

function unitsUp(px: number, axis: 'w' | 'h'): number {
  return Math.max(1, Math.ceil(px / SIZE_UNIT_PX[axis]));
}

export interface HarnessWidget {
  key: string;
  manifest: string;
  slot: SlotId;
  target: string | null;
  zones: FitZone[];
  sizes: Partial<Record<FitZone, StandardSize[]>>;
}


function slotFor(manifestId: string): SlotId | null {
  const cell = manifestId.replace(/^core\./, '');
  if (cell === 'terminal') return FIXTURE_TERMINAL_SLOT;
  if (cell === 'browser') return FIXTURE_BROWSER_SLOT;
  if (cell === 'analytics') return null;
  return cell as SlotId;
}

function entry(key: string, manifest: string, slot: SlotId, floor?: { width: number; height: number }, onlyZones?: readonly FitZone[]): HarnessWidget | null {
  const declared = fitsForSlot(slot);
  if (!declared) return null;
  const record = metaFor(slot, META);
  const meta = floor ? { ...record, minPx: Math.max(record.minPx, floor.width), minHeight: Math.max(record.minHeight, floor.height) } : record;
  const fits = floor ? { ...declared, min: { w: Math.max(declared.min.w, unitsUp(meta.minPx, 'w')), h: Math.max(declared.min.h, unitsUp(meta.minHeight, 'h')) } } : declared;
  const sizes: Partial<Record<FitZone, StandardSize[]>> = {};
  const zones = [...(onlyZones ?? HARNESS_ZONES)];
  const glance = declaredGlanceHeight(manifest) ?? GLANCE_TILE_HEIGHT_PX;
  for (const zone of zones) sizes[zone] = standardSizes(meta, zone, glance, suggestedSizes(fits));
  const colon = slot.indexOf(':');
  return { key, manifest, slot, target: colon < 0 ? null : slot.slice(colon + 1), zones, sizes };
}

export interface DraftEntry {
  key: string;
  slot: SlotId;
  zones: readonly FitZone[];
}

const DRAFT_ENTRIES: DraftEntry[] = [];

export function registerDraftEntry(draft: DraftEntry): void {
  DRAFT_ENTRIES.push(draft);
}

export function harnessWidgets(): HarnessWidget[] {
  const out: HarnessWidget[] = [];
  for (const id of Object.keys(CORE_MANIFESTS)) {
    if (id === 'core.analytics') {
      for (const preset of PRESETS) {
        const one = entry(`core.analytics:${preset.id}`, id, `analytics:${fixtureChartId(preset.id)}` as SlotId, VIZ_SPECS[preset.viz].min);
        if (one) out.push(one);
      }
      continue;
    }
    const slot = slotFor(id);
    const one = slot ? entry(id, id, slot) : null;
    if (one) out.push(one);
  }
  for (const draft of DRAFT_ENTRIES) {
    const one = entry(draft.key, draft.key, draft.slot, undefined, draft.zones);
    if (one) out.push(one);
  }
  return out;
}

export function harnessWidget(key: string): HarnessWidget | undefined {
  return harnessWidgets().find((one) => one.key === key);
}

import type { RailEdge } from './rail-model';
import { BAR_GRAB_MIN_PX, clampBar } from './bar-limits';
import { barThickness } from '../widget-bars/bar-size';
import type { BarSize } from '../widget-bars/bar-settings.svelte';

export const OUT_DEFAULT_PX: Readonly<Record<RailEdge, number>> = Object.freeze({ side: 380, bottom: 320 });

export const OUT_STEP_PX = 16;

/* must hold still */
export const RAIL_PUSH_DEBOUNCE_MS = 120;

export interface SizeStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export function sizeKey(edge: RailEdge): string {
  return `carnivore.session.rail.out.${edge}`;
}

export function outMinPx(edge: RailEdge, size: BarSize): number {
  return edge === 'side' ? BAR_GRAB_MIN_PX : barThickness('bottom', size);
}

export function clampOut(px: number, room: number, edge: RailEdge = 'side', size: BarSize = 'cozy'): number {
  return clampBar(px, room, edge === 'side' ? 'x' : 'y', undefined, outMinPx(edge, size));
}

export function readOutSize(edge: RailEdge, storage: SizeStorage | null = deviceStorage()): number | null {
  if (!storage) return null;
  let raw: string | null = null;
  try {
    raw = storage.getItem(sizeKey(edge));
  } catch {
    return null;
  }
  if (raw === null) return null;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : null;
}

export function writeOutSize(edge: RailEdge, px: number, storage: SizeStorage | null = deviceStorage()): void {
  if (!storage) return;
  try {
    storage.setItem(sizeKey(edge), String(Math.round(px)));
  } catch {
  }
}

export function deviceStorage(): SizeStorage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

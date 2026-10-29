import type { CellSize } from '../engine/types';
import { pickState } from '../lib/states';

export type Tier = 'tile' | 'panel' | 'full';
export const TIERS: readonly Tier[] = ['tile', 'panel', 'full'];

export const TIER_WIDTHS: CellSize[] = [{ name: 'tile', min: 0 }, { name: 'panel', min: 300 }, { name: 'full', min: 560 }];
export const TIER_HEIGHTS: CellSize[] = [{ name: 'tile', min: 0 }, { name: 'panel', min: 190 }, { name: 'full', min: 330 }];

export function tierOf(widthStep: string, heightStep: string): Tier {
  const lowest = Math.min(TIERS.indexOf(widthStep as Tier), TIERS.indexOf(heightStep as Tier));
  return TIERS[Math.max(0, lowest)] as Tier;
}

export function pickTier(width: number, height: number, previous?: { w?: string; h?: string }): { w: string; h: string; tier: Tier } {
  const w = pickState(TIER_WIDTHS, width, previous?.w);
  const h = pickState(TIER_HEIGHTS, height, previous?.h);
  return { w, h, tier: tierOf(w, h) };
}

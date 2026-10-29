
import { pickState } from '../lib/states';
import type { DensityLadders, DensityTier, WidgetBounds, WidgetDensity } from './types';

export interface TierRange {
  name: string;
  min: number;
  max: number | null;
}

export function tierRanges(ladder: readonly DensityTier[], ceiling?: number): TierRange[] {
  return ladder.map((tier, index) => {
    const next = ladder[index + 1];
    return { name: tier.name, min: tier.min, max: next ? next.min - 1 : (ceiling ?? null) };
  });
}

export function densityRanges(
  densities: DensityLadders,
  bounds: WidgetBounds,
): { width: TierRange[]; height: TierRange[] } {
  return { width: tierRanges(densities.width, bounds.maxW), height: tierRanges(densities.height, bounds.maxH) };
}

export function resolveDensity(
  densities: DensityLadders,
  box: { width: number; height: number },
  previous?: WidgetDensity,
): WidgetDensity {
  return {
    width: pickState(densities.width, box.width, previous?.width),
    height: pickState(densities.height, box.height, previous?.height),
  };
}

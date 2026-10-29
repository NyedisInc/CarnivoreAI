import type { PlacementOptions } from '../../widgets/placement-options';

export const DENSITY_OPTION = 'density';

export type SessionsDensity = 'compact' | 'normal';

export const NAME_LINES: Readonly<Record<SessionsDensity, number>> = { compact: 1, normal: 2 };

export function densityOf(options: PlacementOptions | undefined): SessionsDensity {
  return options?.[DENSITY_OPTION] === 'compact' ? 'compact' : 'normal';
}

export function nameLines(options: PlacementOptions | undefined, choosable: boolean): number {
  return choosable ? NAME_LINES[densityOf(options)] : NAME_LINES.compact;
}
